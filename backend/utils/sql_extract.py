"""Pull bare, executable SQL out of an LLM response.

Models tend to wrap SQL in ```sql ... ``` fences and sometimes add a line
of explanation. PostgreSQL chokes on both, so we strip them here.
"""
import re

# Matches a fenced block, with or without the "sql" language tag.
_FENCE = re.compile(r"```(?:sql)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_sql(text: str) -> str:
    if not text:
        return ""
    match = _FENCE.search(text)
    sql = match.group(1) if match else text
    # Trim whitespace and a single trailing semicolon for a clean single statement.
    return sql.strip().rstrip(";").strip()