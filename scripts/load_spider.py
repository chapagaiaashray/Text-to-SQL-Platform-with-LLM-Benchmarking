#!/usr/bin/env python3
"""Load Spider's SQLite databases into PostgreSQL.

Each Spider database (data/spider/database/<db_id>/<db_id>.sqlite) becomes a
PostgreSQL *schema* named <db_id> inside the `spider` database.

Design choices:
  * Identifiers are lowercased + sanitized so LLM-generated, unquoted SQL runs.
  * Column types are inferred from the DATA, not SQLite's declared types, which
    are unreliable in Spider (an ID column may be declared TEXT in one table and
    INTEGER in another, which breaks joins on PostgreSQL). We read each column's
    values: all integers -> BIGINT, all numeric -> DOUBLE PRECISION, else TEXT.
  * Text is decoded defensively (errors="replace") so a stray non-UTF-8 byte
    doesn't fail a whole database.
  * Primary keys are recreated; foreign keys are added best-effort.
  * The read-only `query_executor` role is granted SELECT on each new schema.

Run:
    python scripts/load_spider.py --data-dir data/spider
    python scripts/load_spider.py --data-dir data/spider --db-ids-from data/spider/dev.json
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

import psycopg
from psycopg import sql

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.config import settings  # noqa: E402


# ---- Fallback: SQLite affinity -> Postgres type (used only for all-null cols) ----
def map_sqlite_type(decl: str) -> str:
    d = (decl or "").upper()
    if "INT" in d:
        return "BIGINT"
    if any(k in d for k in ("REAL", "FLOA", "DOUB")):
        return "DOUBLE PRECISION"
    if any(k in d for k in ("NUMERIC", "DECIMAL", "MONEY")):
        return "NUMERIC"
    return "TEXT"


# ---- Data-driven type inference ----
def _looks_int(v) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return True
    if isinstance(v, float):
        return v.is_integer()
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return False
        core = s[1:] if s[:1] in "+-" else s
        if len(core) > 1 and core[0] == "0":   # keep zero-padded codes (e.g. "007") as text
            return False
        try:
            int(s)
            return True
        except ValueError:
            return False
    return False


def _looks_float(v) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return False
        core = s[1:] if s[:1] in "+-" else s
        if len(core) > 1 and core[0] == "0" and not core.startswith("0."):
            return False
        try:
            float(s)
            return True
        except ValueError:
            return False
    return False


def infer_pg_types(declared_types: list[str], rows: list[list]) -> list[str]:
    """Pick a Postgres type per column from the actual values."""
    n = len(declared_types)
    could_int = [True] * n
    could_float = [True] * n
    seen = [False] * n
    for row in rows:
        for i, v in enumerate(row):
            if v is None:
                continue
            seen[i] = True
            if could_int[i] and not _looks_int(v):
                could_int[i] = False
            if could_float[i] and not _looks_float(v):
                could_float[i] = False

    types = []
    for i in range(n):
        if not seen[i]:
            types.append(map_sqlite_type(declared_types[i]))  # no data to judge by
        elif could_int[i]:
            types.append("BIGINT")
        elif could_float[i]:
            types.append("DOUBLE PRECISION")
        else:
            types.append("TEXT")
    return types


def coerce_value(value, pg_type: str):
    """Convert a raw SQLite value into something the inferred column type accepts."""
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if pg_type == "BIGINT":
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        return int(str(value).strip())
    if pg_type == "DOUBLE PRECISION":
        return float(value)
    if isinstance(value, str):
        # scrub any invalid unicode so COPY won't choke
        return value.encode("utf-8", errors="replace").decode("utf-8")
    return value


_IDENT_RE = re.compile(r"[^a-z0-9_]")


def sanitize(name: str) -> str:
    """Lowercase + replace illegal chars so the identifier needs no quoting."""
    s = _IDENT_RE.sub("_", name.strip().lower())
    if not s:
        s = "col"
    if s[0].isdigit():
        s = f"_{s}"
    return s


class SqliteReader:
    """Read schema + data out of a single SQLite file."""

    def __init__(self, path: Path):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        # Decode text defensively so invalid bytes don't raise mid-load.
        self.conn.text_factory = lambda b: b.decode("utf-8", errors="replace")

    def close(self):
        self.conn.close()

    def table_names(self) -> list[str]:
        cur = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        return [r[0] for r in cur.fetchall()]

    def columns(self, table: str) -> list[dict]:
        # PRAGMA returns: cid, name, type, notnull, dflt_value, pk
        cur = self.conn.execute(f'PRAGMA table_info("{table}")')
        return [dict(r) for r in cur.fetchall()]

    def foreign_keys(self, table: str) -> list[dict]:
        cur = self.conn.execute(f'PRAGMA foreign_key_list("{table}")')
        return [dict(r) for r in cur.fetchall()]

    def all_rows(self, table: str) -> list[list]:
        cur = self.conn.execute(f'SELECT * FROM "{table}"')
        return [list(r) for r in cur.fetchall()]


def create_table(pg: psycopg.Connection, schema: str, table: str,
                 col_names: list[str], col_types: list[str], pk_cols: list[tuple]):
    col_defs = [
        sql.SQL("{} {}").format(sql.Identifier(sanitize(n)), sql.SQL(t))
        for n, t in zip(col_names, col_types)
    ]
    parts = list(col_defs)
    if pk_cols:
        pk_ordered = [name for _, name in sorted(pk_cols)]
        parts.append(
            sql.SQL("PRIMARY KEY ({})").format(
                sql.SQL(", ").join(sql.Identifier(n) for n in pk_ordered)
            )
        )
    stmt = sql.SQL("CREATE TABLE {}.{} ({})").format(
        sql.Identifier(schema), sql.Identifier(sanitize(table)),
        sql.SQL(", ").join(parts),
    )
    with pg.cursor() as cur:
        cur.execute(stmt)


def copy_data(pg: psycopg.Connection, schema: str, table: str,
              col_names: list[str], col_types: list[str], rows: list[list]) -> int:
    if not col_names:
        return 0
    tgt_cols = [sanitize(c) for c in col_names]
    copy_stmt = sql.SQL("COPY {}.{} ({}) FROM STDIN").format(
        sql.Identifier(schema), sql.Identifier(sanitize(table)),
        sql.SQL(", ").join(sql.Identifier(c) for c in tgt_cols),
    )
    count = 0
    with pg.cursor() as cur:
        with cur.copy(copy_stmt) as copy:
            for row in rows:
                copy.write_row([coerce_value(v, t) for v, t in zip(row, col_types)])
                count += 1
    return count


def add_foreign_keys(pg: psycopg.Connection, schema: str, table: str, reader: SqliteReader):
    """Add FKs best-effort. Skip (warn) any FK that fails (e.g. dirty data)."""
    fks = reader.foreign_keys(table)
    grouped: dict[int, list[dict]] = {}
    for fk in fks:
        grouped.setdefault(fk["id"], []).append(fk)

    for _id, parts in grouped.items():
        parts.sort(key=lambda p: p["seq"])
        local_cols = [sanitize(p["from"]) for p in parts]
        ref_table = sanitize(parts[0]["table"])
        ref_cols = [sanitize(p["to"]) for p in parts]
        constraint = sql.SQL(
            "ALTER TABLE {sch}.{tbl} ADD FOREIGN KEY ({lcols}) "
            "REFERENCES {sch}.{rtbl} ({rcols})"
        ).format(
            sch=sql.Identifier(schema),
            tbl=sql.Identifier(sanitize(table)),
            lcols=sql.SQL(", ").join(sql.Identifier(c) for c in local_cols),
            rtbl=sql.Identifier(ref_table),
            rcols=sql.SQL(", ").join(sql.Identifier(c) for c in ref_cols),
        )
        try:
            with pg.cursor() as cur:
                cur.execute(constraint)
            pg.commit()
        except Exception as exc:  # noqa: BLE001
            pg.rollback()
            print(f"      [warn] skipped FK on {table}({','.join(local_cols)}): "
                  f"{str(exc).splitlines()[0]}")


def load_database(pg: psycopg.Connection, db_id: str, sqlite_path: Path,
                  executor_role: str) -> dict:
    schema = sanitize(db_id)
    reader = SqliteReader(sqlite_path)
    stats = {"db_id": db_id, "schema": schema, "tables": 0, "rows": 0}
    try:
        with pg.cursor() as cur:
            cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                sql.Identifier(schema)))
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        pg.commit()

        tables = reader.table_names()
        plan = {}  # table -> (col_names, col_types, pk_cols, rows)

        # Pass 1: read data, infer types, create tables.
        for t in tables:
            meta = reader.columns(t)
            col_names = [c["name"] for c in meta]
            declared = [c["type"] for c in meta]
            pk_cols = [(c["pk"], sanitize(c["name"])) for c in meta if c["pk"]]
            rows = reader.all_rows(t)
            col_types = infer_pg_types(declared, rows)
            plan[t] = (col_names, col_types, pk_cols, rows)
            create_table(pg, schema, t, col_names, col_types, pk_cols)
        pg.commit()

        # Pass 2: copy data (coerced to the inferred types).
        for t in tables:
            col_names, col_types, _pk, rows = plan[t]
            stats["rows"] += copy_data(pg, schema, t, col_names, col_types, rows)
        pg.commit()

        # Pass 3: foreign keys (best-effort).
        for t in tables:
            add_foreign_keys(pg, schema, t, reader)
        stats["tables"] = len(tables)

        with pg.cursor() as cur:
            cur.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                sql.Identifier(schema), sql.Identifier(executor_role)))
            cur.execute(sql.SQL(
                "GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}").format(
                sql.Identifier(schema), sql.Identifier(executor_role)))
        pg.commit()
    finally:
        reader.close()
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data/spider")
    ap.add_argument("--dsn", default=None,
                    help="Postgres DSN (default: settings.spider_admin_dsn)")
    ap.add_argument("--only", default=None, help="load just this db_id")
    ap.add_argument("--db-ids-from", default=None,
                    help="load only db_ids referenced in a Spider JSON "
                         "(e.g. data/spider/dev.json) — much faster than all 166")
    ap.add_argument("--limit", type=int, default=None, help="max databases to load")
    ap.add_argument("--executor-role", default=None,
                    help="read-only role to grant SELECT (default from settings)")
    args = ap.parse_args()

    dsn = args.dsn or settings.spider_admin_dsn
    executor_role = args.executor_role or settings.query_executor_user

    db_root = Path(args.data_dir) / "database"
    if not db_root.exists():
        print(f"[!] no database/ dir under {args.data_dir}. "
              "Download Spider or generate the sample first.")
        sys.exit(1)

    sqlite_files = sorted(db_root.glob("*/*.sqlite"))
    if args.only:
        sqlite_files = [p for p in sqlite_files if p.stem == args.only]
    if args.db_ids_from:
        wanted = {ex["db_id"] for ex in json.loads(Path(args.db_ids_from).read_text())}
        sqlite_files = [p for p in sqlite_files if p.stem in wanted]
        print(f"    restricting to {len(wanted)} db_ids from {args.db_ids_from}")
    if args.limit:
        sqlite_files = sqlite_files[: args.limit]

    print(f"==> loading {len(sqlite_files)} database(s) into Postgres")
    print(f"    target: {dsn.rsplit('@', 1)[-1]}")

    total = {"tables": 0, "rows": 0, "dbs": 0}
    with psycopg.connect(dsn) as pg:
        try:
            with pg.cursor() as cur:
                cur.execute(sql.SQL(
                    "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname=%s) "
                    "THEN EXECUTE format('CREATE ROLE %I LOGIN', %s); END IF; END $$"),
                    (executor_role, executor_role))
            pg.commit()
        except Exception:  # noqa: BLE001
            pg.rollback()

        for path in sqlite_files:
            db_id = path.stem
            print(f"  - {db_id} ...", end=" ", flush=True)
            try:
                s = load_database(pg, db_id, path, executor_role)
                total["tables"] += s["tables"]
                total["rows"] += s["rows"]
                total["dbs"] += 1
                print(f"ok ({s['tables']} tables, {s['rows']} rows -> schema '{s['schema']}')")
            except Exception as exc:  # noqa: BLE001
                pg.rollback()
                print(f"FAILED: {str(exc).splitlines()[0]}")

    print(f"\n==> done: {total['dbs']} databases, "
          f"{total['tables']} tables, {total['rows']} rows")


if __name__ == "__main__":
    main()