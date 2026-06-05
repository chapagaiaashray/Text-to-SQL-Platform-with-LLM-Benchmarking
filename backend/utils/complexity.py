"""SQL complexity classification into the project's 5 tiers.

These tiers are defined by THIS project (see context doc), and are distinct
from Spider's official easy/medium/hard/extra-hard labels (which are computed
by Spider's evaluation.py `eval_hardness` from a parsed SQL dict). For
paper-comparable numbers we vendor Spider's evaluator in Week 4; this module
gives us a transparent, dependency-free tiering we control end to end and can
reuse in the live product where no gold parse exists.

Tier 1: Simple SELECT / WHERE / ORDER BY (single table, no aggregation)
Tier 2: JOINs (INNER/LEFT/RIGHT/multi-table FROM)
Tier 3: GROUP BY / HAVING / aggregate functions
Tier 4: Subqueries / correlated subqueries / set ops (IN (SELECT...), EXISTS, UNION)
Tier 5: Window functions / CTEs / deeply nested multi-table
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Aggregate function names that signal Tier 3.
_AGG = r"\b(count|sum|avg|min|max|group_concat|string_agg)\s*\("
# Window function signal: an OVER( ... ) clause.
_WINDOW = r"\bover\s*\("
# CTE signal.
_CTE = r"\bwith\b[\s\S]*?\bas\s*\("
# Set operations.
_SETOP = r"\b(union|intersect|except)\b"


def _strip_strings(sql: str) -> str:
    """Remove string literals so keywords inside them aren't miscounted."""
    sql = re.sub(r"'(?:[^']|'')*'", "''", sql)
    sql = re.sub(r'"(?:[^"]|"")*"', '""', sql)
    return sql


def _count_selects(sql: str) -> int:
    return len(re.findall(r"\bselect\b", sql))


@dataclass
class ComplexityResult:
    tier: int
    features: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return {
            1: "Tier 1: Simple SELECT/WHERE/ORDER BY",
            2: "Tier 2: JOINs",
            3: "Tier 3: GROUP BY/HAVING/aggregates",
            4: "Tier 4: Subqueries / set operations",
            5: "Tier 5: Window functions / CTEs / deep nesting",
        }[self.tier]


def classify_sql(query: str) -> ComplexityResult:
    """Return the highest-matching complexity tier for a SQL string.

    The classifier is monotonic: it detects all present features and assigns
    the maximum tier those features imply. Designed to never raise on
    malformed SQL (returns Tier 1 with no features).
    """
    if not query or not query.strip():
        return ComplexityResult(tier=1, features=[])

    s = _strip_strings(query.lower())
    features: list[str] = []
    tier = 1

    # ---- Tier 2: joins / multiple tables ----
    has_join = bool(re.search(r"\bjoin\b", s))
    # multiple comma-separated tables in FROM (old-style joins)
    from_match = re.search(r"\bfrom\b(.*?)(\bwhere\b|\bgroup\b|\border\b|\bhaving\b|$)", s, re.DOTALL)
    comma_join = bool(from_match and "," in from_match.group(1) and "select" not in from_match.group(1))
    if has_join or comma_join:
        features.append("join")
        tier = max(tier, 2)

    # ---- Tier 3: aggregation ----
    if re.search(_AGG, s):
        features.append("aggregate")
        tier = max(tier, 3)
    if re.search(r"\bgroup\s+by\b", s):
        features.append("group_by")
        tier = max(tier, 3)
    if re.search(r"\bhaving\b", s):
        features.append("having")
        tier = max(tier, 3)

    # ---- Tier 4: subqueries / set ops ----
    if _count_selects(s) > 1 and not re.search(_CTE, s):
        features.append("subquery")
        tier = max(tier, 4)
    if re.search(_SETOP, s):
        features.append("set_operation")
        tier = max(tier, 4)

    # ---- Tier 5: window functions / CTEs / deep nesting ----
    if re.search(_WINDOW, s):
        features.append("window_function")
        tier = max(tier, 5)
    if re.search(_CTE, s):
        features.append("cte")
        tier = max(tier, 5)
    if _count_selects(s) >= 3:
        features.append("deep_nesting")
        tier = max(tier, 5)

    return ComplexityResult(tier=tier, features=features)
