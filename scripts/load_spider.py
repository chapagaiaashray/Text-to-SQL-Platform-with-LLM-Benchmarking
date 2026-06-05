#!/usr/bin/env python3
"""Load Spider's SQLite databases into PostgreSQL.

Each Spider database (data/spider/database/<db_id>/<db_id>.sqlite) becomes a
PostgreSQL *schema* named <db_id> inside the `spider` database. One Postgres
instance, many schemas — easy to introspect and to reset.

Design choices:
  * Identifiers are lowercased + sanitized so that LLM-generated, unquoted SQL
    executes against them (Spider names are already mostly lowercase snake_case).
  * SQLite type affinity is mapped to Postgres types (see TYPE_MAP).
  * Primary keys are recreated; foreign keys are added best-effort (a FK whose
    data violates referential integrity is skipped with a warning rather than
    failing the whole load).
  * The read-only `query_executor` role is granted SELECT on each new schema.

Run (after Postgres is up and Spider is downloaded):
    python scripts/load_spider.py --data-dir data/spider
    python scripts/load_spider.py --data-dir data/spider_sample   # for the sample
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

import psycopg
from psycopg import sql

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.config import settings  # noqa: E402


# ---- SQLite affinity -> Postgres type ----
def map_sqlite_type(decl: str) -> str:
    d = (decl or "").upper()
    if "INT" in d:
        return "BIGINT"
    if any(k in d for k in ("CHAR", "CLOB", "TEXT")):
        return "TEXT"
    if "BLOB" in d or d == "":
        return "BYTEA" if "BLOB" in d else "TEXT"
    if any(k in d for k in ("REAL", "FLOA", "DOUB")):
        return "DOUBLE PRECISION"
    if any(k in d for k in ("NUMERIC", "DECIMAL", "MONEY")):
        return "NUMERIC"
    if "BOOL" in d:
        return "BOOLEAN"
    # DATE/DATETIME in Spider are stored as text; keep as TEXT to avoid parse errors.
    return "TEXT"


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

    def rows(self, table: str):
        cur = self.conn.execute(f'SELECT * FROM "{table}"')
        cols = [c[0] for c in cur.description]
        for r in cur:
            yield list(r), cols


def create_table(pg: psycopg.Connection, schema: str, table: str, reader: SqliteReader):
    cols = reader.columns(table)
    col_defs = []
    pk_cols = []
    for c in cols:
        col_name = sanitize(c["name"])
        pg_type = map_sqlite_type(c["type"])
        col_defs.append(
            sql.SQL("{} {}").format(sql.Identifier(col_name), sql.SQL(pg_type))
        )
        if c["pk"]:
            pk_cols.append((c["pk"], col_name))  # pk is 1-based ordinal for composite

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


def copy_data(pg: psycopg.Connection, schema: str, table: str, reader: SqliteReader) -> int:
    sane_table = sanitize(table)
    src_cols = [c["name"] for c in reader.columns(table)]
    tgt_cols = [sanitize(c) for c in src_cols]
    if not src_cols:
        return 0

    copy_stmt = sql.SQL("COPY {}.{} ({}) FROM STDIN").format(
        sql.Identifier(schema), sql.Identifier(sane_table),
        sql.SQL(", ").join(sql.Identifier(c) for c in tgt_cols),
    )
    count = 0
    with pg.cursor() as cur:
        with cur.copy(copy_stmt) as copy:
            for values, _cols in reader.rows(table):
                copy.write_row(values)
                count += 1
    return count


def add_foreign_keys(pg: psycopg.Connection, schema: str, table: str, reader: SqliteReader):
    """Add FKs best-effort. Skip (warn) any FK that fails (e.g. dirty data)."""
    fks = reader.foreign_keys(table)
    # PRAGMA groups composite FKs by the `id` field; group them.
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
        # Pass 1: create all tables (so FKs in pass 3 can resolve).
        for t in tables:
            create_table(pg, schema, t, reader)
        pg.commit()
        # Pass 2: copy data.
        for t in tables:
            n = copy_data(pg, schema, t, reader)
            stats["rows"] += n
        pg.commit()
        # Pass 3: foreign keys (best-effort).
        for t in tables:
            add_foreign_keys(pg, schema, t, reader)
        stats["tables"] = len(tables)

        # Grant read-only role access to the new schema.
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
    if args.limit:
        sqlite_files = sqlite_files[: args.limit]

    print(f"==> loading {len(sqlite_files)} database(s) into Postgres")
    print(f"    target: {dsn.rsplit('@', 1)[-1]}")  # hide credentials

    total = {"tables": 0, "rows": 0, "dbs": 0}
    with psycopg.connect(dsn) as pg:
        # Make sure the executor role exists (idempotent for non-docker setups).
        try:
            with pg.cursor() as cur:
                cur.execute(sql.SQL(
                    "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname=%s) "
                    "THEN EXECUTE format('CREATE ROLE %I LOGIN', %s); END IF; END $$"),
                    (executor_role, executor_role))
            pg.commit()
        except Exception:  # noqa: BLE001
            pg.rollback()  # role probably exists / insufficient priv; continue

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
