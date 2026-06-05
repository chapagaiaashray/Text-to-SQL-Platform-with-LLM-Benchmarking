"""Integration tests for the schema introspector.

These require a PostgreSQL instance with the sample Spider data loaded:

    docker compose up -d db
    python scripts/make_sample_spider.py --dest data/spider_sample
    python scripts/load_spider.py --data-dir data/spider_sample

Set TEST_SPIDER_DSN to override the connection. Tests skip cleanly if the DB
or expected schema is unavailable, so they won't break a CI run without a DB.
"""
import os

import pytest

from backend.services.schema_introspector import SchemaIntrospector

DSN = os.environ.get(
    "TEST_SPIDER_DSN", "postgresql://postgres@localhost:5432/spider"
)


@pytest.fixture(scope="module")
def intro():
    intro = SchemaIntrospector(DSN)
    try:
        schemas = intro.list_schemas()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no database available: {exc}")
    if "college_1" not in schemas:
        pytest.skip("sample schema 'college_1' not loaded")
    return intro


def test_lists_sample_schemas(intro):
    schemas = intro.list_schemas()
    assert "college_1" in schemas
    assert "pets_1" in schemas


def test_table_discovery(intro):
    tables = set(intro.list_tables("college_1"))
    assert {"student", "course", "enrollment"} <= tables


def test_primary_key_detected(intro):
    student = intro.introspect_table("college_1", "student")
    assert student.primary_key == ["student_id"]


def test_foreign_keys_detected(intro):
    enrollment = intro.introspect_table("college_1", "enrollment")
    refs = {(tuple(fk.columns), fk.referred_table) for fk in enrollment.foreign_keys}
    assert (("student_id",), "student") in refs
    assert (("course_id",), "course") in refs


def test_row_count_and_samples(intro):
    student = intro.introspect_table("college_1", "student", sample_limit=2)
    assert student.row_count == 4
    assert len(student.sample_rows) == 2


def test_prompt_context_contains_ddl_and_samples(intro):
    db = intro.introspect_schema("college_1", sample_limit=3)
    ctx = SchemaIntrospector.to_prompt_context(db)
    assert "CREATE TABLE student" in ctx
    assert "FOREIGN KEY" in ctx
    assert "example row" in ctx
