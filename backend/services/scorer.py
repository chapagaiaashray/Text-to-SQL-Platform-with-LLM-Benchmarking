"""Scores a generated query against the gold query by execution accuracy.

Comparison follows the spirit of Spider's official execution match, adapted to
run on our PostgreSQL results:
  * column order is ignored          (SELECT a, b  ==  SELECT b, a)
  * row order matters only when the gold query has an ORDER BY
  * numbers are normalized so 3, 3.0 and '3' compare equal
  * the column count must match      (extra/missing columns => incorrect)

This is a faithful reimplementation of execution-match accuracy, NOT Spider's
full "test suite" accuracy (which runs each query against multiple distilled
database instances to catch false positives). That remains future work.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from backend.services.sql_executor import ExecutionResult, SQLExecutor
from backend.utils.sql_dialect import normalize_gold_sql

_ORDER_BY = re.compile(r"\border\s+by\b", re.IGNORECASE)


def _norm_cell(value) -> str:
    """Canonicalize one cell so type differences don't cause false mismatches."""
    if value is None:
        return "\u2205"  # sentinel for NULL
    try:
        return format(round(float(value), 6), ".6f")  # 3, 3.0, '3' -> same form
    except (TypeError, ValueError):
        return str(value).strip()


def _fingerprint(rows: list[tuple], order_matters: bool) -> list:
    """Reduce a result set to a comparable, column-order-insensitive form."""
    norm_rows = [tuple(_norm_cell(c) for c in row) for row in rows]
    if not order_matters:
        norm_rows = sorted(norm_rows)            # row order irrelevant
    columns = list(zip(*norm_rows)) if norm_rows else []
    return sorted(columns)                        # column order irrelevant


def results_match(gen: ExecutionResult, gold: ExecutionResult,
                  order_matters: bool) -> bool:
    if gen.columns and gold.columns and len(gen.columns) != len(gold.columns):
        return False  # different column count can't be equal
    return _fingerprint(gen.rows, order_matters) == _fingerprint(gold.rows, order_matters)


@dataclass
class ScoreResult:
    correct: bool
    reason: str
    generated: ExecutionResult
    gold: ExecutionResult


class Scorer:
    def __init__(self, executor: SQLExecutor | None = None):
        self.executor = executor or SQLExecutor()

    def score(self, generated_sql: str, gold_sql: str, schema_name: str) -> ScoreResult:
        gold = self.executor.execute(normalize_gold_sql(gold_sql), schema_name)
        if not gold.success:
            return ScoreResult(False, f"gold query failed: {gold.error}",
                               self.executor.execute(generated_sql, schema_name), gold)

        gen = self.executor.execute(generated_sql, schema_name)
        if not gen.success:
            return ScoreResult(False, f"generated query failed: {gen.error}", gen, gold)

        order_matters = bool(_ORDER_BY.search(gold_sql))
        if results_match(gen, gold, order_matters):
            return ScoreResult(True, "result sets match", gen, gold)
        return ScoreResult(False, "result sets differ", gen, gold)