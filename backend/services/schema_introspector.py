"""Schema introspector.

Reads the full structure of any PostgreSQL database/schema: tables, columns
(type, nullability, default), primary keys, foreign keys, row counts, and a
handful of sample rows per table. Produces typed DatabaseSchema objects and
can render CREATE-TABLE-style DDL plus sample data for LLM prompting.

Usage:
    intro = SchemaIntrospector(dsn)
    db = intro.introspect_schema("college_1", sample_limit=3)
    print(intro.to_prompt_context(db))
"""
from __future__ import annotations

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from backend.models.schemas import (
    ColumnInfo,
    DatabaseSchema,
    ForeignKey,
    TableSchema,
)


class SchemaIntrospector:
    def __init__(self, dsn: str):
        self.dsn = dsn

    # ---- connection helper ----
    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.dsn, row_factory=dict_row)

    # ---- discovery ----
    def list_schemas(self) -> list[str]:
        """User schemas (excludes system + information_schema)."""
        q = """
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name NOT IN ('pg_catalog', 'information_schema')
              AND schema_name NOT LIKE 'pg_%'
            ORDER BY schema_name
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(q)
            return [r["schema_name"] for r in cur.fetchall()]

    def list_tables(self, schema: str) -> list[str]:
        q = """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(q, (schema,))
            return [r["table_name"] for r in cur.fetchall()]

    # ---- per-table metadata ----
    def _columns(self, conn, schema: str, table: str) -> list[ColumnInfo]:
        q = """
            SELECT column_name, data_type, is_nullable,
                   column_default, ordinal_position
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
        """
        with conn.cursor() as cur:
            cur.execute(q, (schema, table))
            return [
                ColumnInfo(
                    name=r["column_name"],
                    data_type=r["data_type"],
                    is_nullable=(r["is_nullable"] == "YES"),
                    default=r["column_default"],
                    ordinal=r["ordinal_position"],
                )
                for r in cur.fetchall()
            ]

    def _primary_key(self, conn, schema: str, table: str) -> list[str]:
        # pg_catalog is more reliable than information_schema for ordered,
        # composite primary keys.
        q = """
            SELECT a.attname AS col
            FROM pg_index i
            JOIN pg_class c       ON c.oid = i.indrelid
            JOIN pg_namespace n   ON n.oid = c.relnamespace
            JOIN pg_attribute a   ON a.attrelid = c.oid
                                 AND a.attnum = ANY(i.indkey)
            WHERE n.nspname = %s AND c.relname = %s AND i.indisprimary
            ORDER BY array_position(i.indkey, a.attnum)
        """
        with conn.cursor() as cur:
            cur.execute(q, (schema, table))
            return [r["col"] for r in cur.fetchall()]

    def _foreign_keys(self, conn, schema: str, table: str) -> list[ForeignKey]:
        # Pair local columns (conkey) with referenced columns (confkey) using
        # WITH ORDINALITY so composite FKs keep their column order.
        q = """
            SELECT
                con.conname AS name,
                ns2.nspname AS ref_schema,
                cl2.relname AS ref_table,
                array_agg(att.attname  ORDER BY u.ord)  AS local_cols,
                array_agg(att2.attname ORDER BY u.ord)  AS ref_cols
            FROM pg_constraint con
            JOIN pg_class cl       ON cl.oid = con.conrelid
            JOIN pg_namespace ns   ON ns.oid = cl.relnamespace
            JOIN pg_class cl2      ON cl2.oid = con.confrelid
            JOIN pg_namespace ns2  ON ns2.oid = cl2.relnamespace
            JOIN LATERAL unnest(con.conkey, con.confkey)
                 WITH ORDINALITY AS u(conkey, confkey, ord) ON TRUE
            JOIN pg_attribute att  ON att.attrelid = con.conrelid
                                  AND att.attnum = u.conkey
            JOIN pg_attribute att2 ON att2.attrelid = con.confrelid
                                  AND att2.attnum = u.confkey
            WHERE ns.nspname = %s AND cl.relname = %s AND con.contype = 'f'
            GROUP BY con.conname, ns2.nspname, cl2.relname
            ORDER BY con.conname
        """
        with conn.cursor() as cur:
            cur.execute(q, (schema, table))
            return [
                ForeignKey(
                    name=r["name"],
                    columns=list(r["local_cols"]),
                    referred_schema=r["ref_schema"],
                    referred_table=r["ref_table"],
                    referred_columns=list(r["ref_cols"]),
                )
                for r in cur.fetchall()
            ]

    def _row_count(self, conn, schema: str, table: str) -> int:
        q = sql.SQL("SELECT count(*) AS n FROM {}.{}").format(
            sql.Identifier(schema), sql.Identifier(table))
        with conn.cursor() as cur:
            cur.execute(q)
            return cur.fetchone()["n"]

    def _sample_rows(self, conn, schema: str, table: str, limit: int) -> list[dict]:
        if limit <= 0:
            return []
        q = sql.SQL("SELECT * FROM {}.{} LIMIT %s").format(
            sql.Identifier(schema), sql.Identifier(table))
        with conn.cursor() as cur:
            cur.execute(q, (limit,))
            return [dict(r) for r in cur.fetchall()]

    def introspect_table(self, schema: str, table: str, *,
                         sample_limit: int = 3,
                         include_row_count: bool = True) -> TableSchema:
        with self._connect() as conn:
            columns = self._columns(conn, schema, table)
            pk = set(self._primary_key(conn, schema, table))
            for col in columns:
                col.is_primary_key = col.name in pk
            fks = self._foreign_keys(conn, schema, table)
            row_count = self._row_count(conn, schema, table) if include_row_count else None
            sample = self._sample_rows(conn, schema, table, sample_limit)
        return TableSchema(
            schema_name=schema, name=table, columns=columns,
            primary_key=[c.name for c in columns if c.is_primary_key],
            foreign_keys=fks, row_count=row_count, sample_rows=sample,
        )

    def introspect_schema(self, schema: str, *,
                          sample_limit: int = 3,
                          include_row_count: bool = True) -> DatabaseSchema:
        tables = [
            self.introspect_table(
                schema, t, sample_limit=sample_limit,
                include_row_count=include_row_count,
            )
            for t in self.list_tables(schema)
        ]
        return DatabaseSchema(schema_name=schema, tables=tables)

    # ---- rendering for prompts ----
    @staticmethod
    def table_ddl(table: TableSchema) -> str:
        """Reconstruct a readable CREATE TABLE statement."""
        lines = [f"CREATE TABLE {table.name} ("]
        col_lines = []
        for c in table.columns:
            parts = [f"  {c.name} {c.data_type.upper()}"]
            if not c.is_nullable:
                parts.append("NOT NULL")
            col_lines.append(" ".join(parts))
        if table.primary_key:
            col_lines.append(f"  PRIMARY KEY ({', '.join(table.primary_key)})")
        for fk in table.foreign_keys:
            col_lines.append(
                f"  FOREIGN KEY ({', '.join(fk.columns)}) "
                f"REFERENCES {fk.referred_table} ({', '.join(fk.referred_columns)})"
            )
        lines.append(",\n".join(col_lines))
        lines.append(");")
        return "\n".join(lines)

    @classmethod
    def _sample_block(cls, table: TableSchema) -> str:
        if not table.sample_rows:
            return ""
        cols = [c.name for c in table.columns]
        header = " | ".join(cols)
        rows = [
            " | ".join(str(r.get(c, "")) for c in cols)
            for r in table.sample_rows
        ]
        body = "\n".join(rows)
        return f"/* {len(table.sample_rows)} example row(s):\n{header}\n{body}\n*/"

    @classmethod
    def to_prompt_context(cls, db: DatabaseSchema, *,
                          include_samples: bool = True) -> str:
        """Render the whole schema as DDL + sample data for an LLM prompt.

        This is the artifact the schema-aware prompt strategy (Week 2) injects.
        """
        blocks = []
        for t in db.tables:
            block = cls.table_ddl(t)
            if include_samples:
                sample = cls._sample_block(t)
                if sample:
                    block += "\n" + sample
            blocks.append(block)
        return "\n\n".join(blocks)
