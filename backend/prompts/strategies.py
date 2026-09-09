"""Prompt strategies for text-to-SQL.

Each strategy turns a question + the introspected schema into a system+user
prompt. They differ in how much context they give the model and whether they
ask it to reason. That difference is the research variable we benchmark.

The output rules in the system prompt are shared across strategies on purpose:
the only thing that should vary between strategies is the context they supply,
not what shape of answer they ask for.
"""
from dataclasses import dataclass

from backend.models.schemas import DatabaseSchema
from backend.services.schema_introspector import SchemaIntrospector


@dataclass
class Prompt:
    system: str
    user: str
    max_tokens: int | None = None   # chain-of-thought needs more room


# Output rules shared by every strategy. The column rule exists because the
# model's most common failure was returning extra "helpful" columns (a count,
# an id, a sort key) that the question never asked for, which fails an
# execution-accuracy comparison against the gold result.
_OUTPUT_RULES = (
    "Select only the columns the question asks for. Do not add extra columns "
    "such as counts, ids, or sort keys unless the question requests them. "
    "Avoid SELECT * unless the question asks for all columns."
)

_SYSTEM = (
    "You translate natural-language questions into PostgreSQL queries. "
    "Reply with a single SQL query using only the tables and columns shown. "
    f"{_OUTPUT_RULES} "
    "Return only the SQL. No prose, no markdown."
)

_SYSTEM_COT = (
    "You translate natural-language questions into PostgreSQL queries. "
    f"{_OUTPUT_RULES} "
    "Reason step by step, then give the final answer as a single SQL query "
    "inside a ```sql code block."
)


def _minimal(db: DatabaseSchema) -> str:
    # table(col, col, ...) — names only, nothing else.
    return "\n".join(
        f"{t.name}(" + ", ".join(c.name for c in t.columns) + ")"
        for t in db.tables
    )


def _full(db: DatabaseSchema) -> str:
    # Full DDL + sample rows, courtesy of the introspector.
    return SchemaIntrospector.to_prompt_context(db)


# Generic, schema-agnostic examples. They show the input->output shape without
# leaking answers. Real few-shot retrieval comes later (RAG, Week 6).
_FEWSHOT = [
    ("How many rows are there?", "SELECT COUNT(*) FROM some_table"),
    ("List the distinct categories.", "SELECT DISTINCT category FROM some_table"),
]


def zero_shot(question: str, db: DatabaseSchema) -> Prompt:
    user = (
        f"Schema:\n{_minimal(db)}\n\n"
        f"Question: {question}\n\n"
        "Write a single PostgreSQL query."
    )
    return Prompt(_SYSTEM, user)


def schema_aware(question: str, db: DatabaseSchema) -> Prompt:
    user = (
        f"Database schema:\n{_full(db)}\n\n"
        f"Question: {question}\n\n"
        "Write a single PostgreSQL query that answers the question."
    )
    return Prompt(_SYSTEM, user)


def few_shot(question: str, db: DatabaseSchema) -> Prompt:
    examples = "\n".join(f"Q: {q}\nSQL: {s}" for q, s in _FEWSHOT)
    user = (
        f"Database schema:\n{_full(db)}\n\n"
        f"Examples:\n{examples}\n\n"
        f"Q: {question}\nSQL:"
    )
    return Prompt(_SYSTEM, user)


def chain_of_thought(question: str, db: DatabaseSchema) -> Prompt:
    user = (
        f"Database schema:\n{_full(db)}\n\n"
        f"Question: {question}\n\n"
        "Think step by step: identify the relevant tables, the joins needed, "
        "and any filters or grouping. Then write the final PostgreSQL query."
    )
    return Prompt(_SYSTEM_COT, user, max_tokens=900)

def rag_few_shot(question: str, db: DatabaseSchema,
                 examples: list | None = None) -> Prompt:
    """Full schema plus examples retrieved from the training split.

    Differs from few_shot only in that the examples are semantically similar
    to this question rather than generic and hardcoded. That difference is the
    variable under test.
    """
    if not examples:
        return schema_aware(question, db)   # graceful fallback
    shown = "\n\n".join(f"Q: {e.question}\nSQL: {e.sql}" for e in examples)
    user = (
        f"Database schema:\n{_full(db)}\n\n"
        f"Similar solved questions (from other databases, for reference only — "
        f"use the schema above for table and column names):\n{shown}\n\n"
        f"Q: {question}\nSQL:"
    )
    return Prompt(_SYSTEM, user)


STRATEGIES = {
    "zero_shot": zero_shot,
    "schema_aware": schema_aware,
    "few_shot": few_shot,
    "chain_of_thought": chain_of_thought,
    "rag_few_shot": rag_few_shot,
    "rag_adaptive": rag_few_shot,
}


def build(name: str, question: str, db: DatabaseSchema) -> Prompt:
    return STRATEGIES[name](question, db)