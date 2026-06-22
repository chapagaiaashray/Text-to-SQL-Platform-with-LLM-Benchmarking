"""Scores a generated query against the gold query by execution accuracy:
run both, compare their result sets.

This is a deliberately simple comparison (order-insensitive multiset of rows).
It does NOT yet handle every edge case the official Spider evaluator does —
notably column ordering and extra columns. We vendor Spider's evaluation.py
in Week 4 for paper-comparable numbers; this is enough to drive development.
"""
from dataclasses import dataclass

from backend.services.sql_executor import ExecutionResult, SQLExecutor


def _normalize(rows: list[tuple]) -> list[tuple]:
    # Stringify cells and sort, so row order doesn't matter in the comparison.
    return sorted(tuple(str(c) for c in row) for row in rows)


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
        gold = self.executor.execute(gold_sql, schema_name)
        if not gold.success:
            # If the gold query itself fails, the test case is broken, not the model.
            return ScoreResult(False, f"gold query failed: {gold.error}", 
                               self.executor.execute(generated_sql, schema_name), gold)

        gen = self.executor.execute(generated_sql, schema_name)
        if not gen.success:
            return ScoreResult(False, f"generated query failed: {gen.error}", gen, gold)

        if _normalize(gen.rows) == _normalize(gold.rows):
            return ScoreResult(True, "result sets match", gen, gold)
        return ScoreResult(False, "result sets differ", gen, gold)