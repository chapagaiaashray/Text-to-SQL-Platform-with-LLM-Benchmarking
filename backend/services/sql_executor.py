"""Runs SQL against the database in a read-only sandbox.

Connects as the read-only `query_executor` role, so generated SQL can never
mutate data. Sets the search_path to the target schema (so unqualified table
names resolve) and a statement timeout (so a bad query can't hang). Returns
the rows on success, or the error message on failure — a failed query is data.
"""
from dataclasses import dataclass, field

import psycopg
from psycopg import sql

from backend.config import settings


@dataclass
class ExecutionResult:
    success: bool
    rows: list[tuple] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def row_count(self) -> int:
        return len(self.rows)


class SQLExecutor:
    def __init__(self, dsn: str | None = None, timeout_ms: int | None = None):
        # Read-only role by default — this is the sandbox.
        self.dsn = dsn or settings.spider_readonly_dsn
        self.timeout_ms = timeout_ms or settings.query_timeout_ms

    def execute(self, query: str, schema_name: str) -> ExecutionResult:
        try:
            with psycopg.connect(self.dsn, connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        sql.SQL("SET statement_timeout = {}").format(
                            sql.Literal(self.timeout_ms)))
                    cur.execute(
                        sql.SQL("SET search_path TO {}").format(
                            sql.Identifier(schema_name)))
                    cur.execute(query)
                    if cur.description is None:      # no result set (e.g. empty)
                        return ExecutionResult(success=True)
                    columns = [d.name for d in cur.description]
                    rows = cur.fetchall()
            return ExecutionResult(success=True, rows=rows, columns=columns)
        except Exception as exc:
            # First line only — keeps long Postgres errors readable.
            return ExecutionResult(success=False, error=str(exc).splitlines()[0])