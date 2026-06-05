"""Tests for the SQL complexity tier classifier."""
from backend.utils.complexity import classify_sql


def test_tier1_simple_select():
    assert classify_sql("SELECT name FROM student").tier == 1
    assert classify_sql("SELECT * FROM t WHERE x > 1 ORDER BY x").tier == 1


def test_tier2_joins():
    r = classify_sql("SELECT a.x FROM a JOIN b ON a.id = b.id")
    assert r.tier == 2
    assert "join" in r.features


def test_tier2_comma_join():
    assert classify_sql("SELECT * FROM a, b WHERE a.id = b.id").tier == 2


def test_tier3_aggregate_and_group():
    r = classify_sql("SELECT dept, count(*) FROM emp GROUP BY dept HAVING count(*) > 5")
    assert r.tier == 3
    assert {"aggregate", "group_by", "having"} <= set(r.features)


def test_tier4_subquery():
    r = classify_sql("SELECT name FROM s WHERE gpa > (SELECT avg(gpa) FROM s)")
    assert r.tier == 4
    assert "subquery" in r.features


def test_tier4_set_operation():
    assert classify_sql("SELECT x FROM a UNION SELECT x FROM b").tier == 4


def test_tier5_window_function():
    r = classify_sql("SELECT x, rank() OVER (PARTITION BY g ORDER BY x) FROM t")
    assert r.tier == 5
    assert "window_function" in r.features


def test_tier5_cte():
    r = classify_sql("WITH cte AS (SELECT 1 AS x) SELECT * FROM cte")
    assert r.tier == 5
    assert "cte" in r.features


def test_string_literal_does_not_trigger_join():
    # 'join' inside a string literal must not be counted as a JOIN.
    assert classify_sql("SELECT * FROM t WHERE note = 'please join us'").tier == 1


def test_empty_is_tier1():
    assert classify_sql("").tier == 1
    assert classify_sql("   ").tier == 1
