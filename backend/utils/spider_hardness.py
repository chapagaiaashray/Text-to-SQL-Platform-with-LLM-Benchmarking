"""Official Spider query-hardness tiers (easy / medium / hard / extra).

Reimplementation of `eval_hardness` from Spider's evaluation.py. It reads the
parsed `sql` dict that ships with every dev.json / train_spider.json example,
counting SQL components to assign a difficulty label.

This is distinct from our own 5-tier classifier in utils/complexity.py: this
one exists so accuracy can be reported per difficulty in the same buckets
published Spider results use.
"""
from __future__ import annotations

# Index positions must match Spider's evaluation.py.
AGG_OPS = ("none", "max", "min", "count", "sum", "avg")
WHERE_OPS = ("not", "between", "=", ">", "<", ">=", "<=", "!=", "in",
             "like", "is", "exists")
_LIKE = WHERE_OPS.index("like")


def _has_agg(unit) -> bool:
    return unit[0] != AGG_OPS.index("none")


def _count_agg(units) -> int:
    return len([u for u in units if _has_agg(u)])


def _nested(sql: dict) -> list[dict]:
    """Sub-SELECTs hiding in conditions, plus intersect/except/union."""
    out = []
    conds = sql["from"]["conds"][::2] + sql["where"][::2] + sql["having"][::2]
    for cond in conds:
        if isinstance(cond[3], dict):
            out.append(cond[3])
        if isinstance(cond[4], dict):
            out.append(cond[4])
    for key in ("intersect", "except", "union"):
        if sql.get(key) is not None:
            out.append(sql[key])
    return out


def _count_component1(sql: dict) -> int:
    """WHERE / GROUP BY / ORDER BY / LIMIT / joins / OR / LIKE."""
    count = 0
    if len(sql["where"]) > 0:
        count += 1
    if len(sql["groupBy"]) > 0:
        count += 1
    if len(sql["orderBy"]) > 0:
        count += 1
    if sql["limit"] is not None:
        count += 1
    if len(sql["from"]["table_units"]) > 0:      # each extra table is a join
        count += len(sql["from"]["table_units"]) - 1

    ao = sql["from"]["conds"][1::2] + sql["where"][1::2] + sql["having"][1::2]
    count += len([t for t in ao if t == "or"])

    conds = sql["from"]["conds"][::2] + sql["where"][::2] + sql["having"][::2]
    count += len([c for c in conds if c[1] == _LIKE])
    return count


def _count_component2(sql: dict) -> int:
    return len(_nested(sql))


def _count_others(sql: dict) -> int:
    """Multiple aggregations / select columns / where conds / group-bys."""
    count = 0

    agg_count = _count_agg(sql["select"][1])
    agg_count += _count_agg(sql["where"][::2])
    agg_count += _count_agg(sql["groupBy"])
    if len(sql["orderBy"]) > 0:
        agg_count += _count_agg(
            [u[1] for u in sql["orderBy"][1] if u[1]]
            + [u[2] for u in sql["orderBy"][1] if u[2]]
        )
    agg_count += _count_agg(sql["having"])
    if agg_count > 1:
        count += 1

    if len(sql["select"][1]) > 1:
        count += 1
    if len(sql["where"]) > 1:
        count += 1
    if len(sql["groupBy"]) > 1:
        count += 1
    return count


def eval_hardness(sql: dict) -> str:
    """Return 'easy' | 'medium' | 'hard' | 'extra' for a parsed Spider sql dict."""
    c1 = _count_component1(sql)
    c2 = _count_component2(sql)
    others = _count_others(sql)

    if c1 <= 1 and others == 0 and c2 == 0:
        return "easy"
    if (others <= 2 and c1 <= 1 and c2 == 0) or (c1 <= 2 and others < 2 and c2 == 0):
        return "medium"
    if (
        (others > 2 and c1 <= 2 and c2 == 0)
        or (2 < c1 <= 3 and others <= 2 and c2 == 0)
        or (c1 <= 1 and others == 0 and c2 <= 1)
    ):
        return "hard"
    return "extra"