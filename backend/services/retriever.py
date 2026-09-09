"""Retrieves similar solved questions from the Spider training split.

Embeds an incoming question and finds the nearest training questions by
cosine similarity, returning their gold SQL as worked examples for the prompt.

Only the TRAIN split is indexed (see scripts/build_rag_index.py), so a dev
question can never retrieve its own answer.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import chromadb
from sentence_transformers import SentenceTransformer

INDEX_DIR = "chroma_db"
COLLECTION = "spider_train"
MODEL = "all-MiniLM-L6-v2"


@dataclass
class RetrievedExample:
    question: str
    sql: str
    db_id: str
    distance: float


@lru_cache(maxsize=1)
def _model() -> SentenceTransformer:
    # Loading the model takes a few seconds; do it once per process.
    return SentenceTransformer(MODEL)


class ExampleRetriever:
    def __init__(self, k: int = 3):
        self.k = k
        client = chromadb.PersistentClient(path=INDEX_DIR)
        self.collection = client.get_collection(COLLECTION)

    def retrieve(self, question: str, k: int | None = None) -> list[RetrievedExample]:
        embedding = _model().encode([question])[0].tolist()
        res = self.collection.query(
            query_embeddings=[embedding],
            n_results=k or self.k,
        )
        out = []
        for doc, meta, dist in zip(
            res["documents"][0], res["metadatas"][0], res["distances"][0]
        ):
            out.append(RetrievedExample(
                question=doc, sql=meta["sql"], db_id=meta["db_id"], distance=dist,
            ))
        return out