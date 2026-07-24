"""Normalize SQLite-dialect gold SQL so it executes on PostgreSQL.

Spider's gold queries target SQLite, which tolerates double-quoted string
literals (e.g. WHERE name = "Angola"). PostgreSQL reads double quotes as an
identifier, so those must become single-quoted strings. We only convert a
double-quoted token when it appears in a *value* position (right after a
comparison operator or IN/LIKE), to avoid corrupting genuine quoted identifiers.
"""
import re

# A double-quoted token that immediately follows a value-introducing operator.
# Group 1 = the operator/keyword + spacing; group 2 = the inner string.
_VALUE_DQUOTE = re.compile(
    r'([=<>!]=?\s*|\bIN\s*\(\s*|\bLIKE\s+|,\s*)"([^"]*)"',
    re.IGNORECASE,
)


def _single_quote(inner: str) -> str:
    # Escape any single quotes inside the string by doubling them (SQL rule).
    return "'" + inner.replace("'", "''") + "'"


def normalize_gold_sql(query: str) -> str:
    """Rewrite SQLite-isms so a Spider gold query runs on PostgreSQL."""
    if not query:
        return query

    # "value" -> 'value' only in value positions.
    def repl(m: re.Match) -> str:
        return m.group(1) + _single_quote(m.group(2))

    return _VALUE_DQUOTE.sub(repl, query)