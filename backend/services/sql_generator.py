"""Text-to-SQL generator: introspector + prompt strategy + LLM router + cleanup.

The strategy is pluggable so we can benchmark all four. Introspected schemas
are cached per database to avoid redundant catalog queries across strategies.
"""
from dataclasses import dataclass

from backend.config import settings
from backend.prompts import strategies
from backend.services.llm_router import LLMRouter
from backend.services.schema_introspector import SchemaIntrospector
from backend.utils.sql_extract import extract_sql
from backend.services.retriever import ExampleRetriever


@dataclass
class GenerationResult:
    question: str
    schema_name: str
    strategy: str
    sql: str
    raw_response: str
    cost_usd: float
    input_tokens: int
    output_tokens: int


class SQLGenerator:
    def __init__(self, dsn: str | None = None, router: LLMRouter | None = None,
                 strategy: str = "schema_aware", retriever: ExampleRetriever | None = None,
                 retrieval_threshold: float | None = None):
        self.dsn = dsn or settings.spider_admin_dsn
        self.introspector = SchemaIntrospector(self.dsn)
        self.router = router or LLMRouter()
        self.strategy = strategy
        self._schema_cache: dict = {}
        # rag_adaptive drops retrieved examples that aren't close enough,
        # falling back to schema-only prompting when nothing qualifies.
        self.retrieval_threshold = retrieval_threshold
        if strategy in ("rag_few_shot", "rag_adaptive"):
            self.retriever = retriever or ExampleRetriever(k=3)
        else:
            self.retriever = None
        self.retrieval_used = 0      # how often examples actually made it in
        self.retrieval_skipped = 0

    def _get_schema(self, schema_name: str, sample_limit: int):
        key = (schema_name, sample_limit)
        if key not in self._schema_cache:
            self._schema_cache[key] = self.introspector.introspect_schema(
                schema_name, sample_limit=sample_limit)
        return self._schema_cache[key]

    def generate(self, question: str, schema_name: str,
                 *, sample_limit: int = 3) -> GenerationResult:
        db = self._get_schema(schema_name, sample_limit)
        if self.retriever:
            examples = self.retriever.retrieve(question)
            if self.retrieval_threshold is not None:
                examples = [e for e in examples if e.distance < self.retrieval_threshold]
            if examples:
                self.retrieval_used += 1
            else:
                self.retrieval_skipped += 1
            prompt = strategies.rag_few_shot(question, db, examples)
        else:
            prompt = strategies.build(self.strategy, question, db)
        resp = self.router.generate(
            prompt.user, system=prompt.system, max_tokens=prompt.max_tokens)
        return GenerationResult(
            question=question,
            schema_name=schema_name,
            strategy=self.strategy,
            sql=extract_sql(resp.text),
            raw_response=resp.text,
            cost_usd=resp.cost_usd,
            input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens,
        )