"""Index Spider's training questions in ChromaDB for retrieval.

Embeds the 7,000 train_spider.json questions and stores each alongside its
gold SQL and db_id. At generation time we retrieve the most similar questions
and show their solved SQL as examples.

IMPORTANT: only the TRAIN split is indexed. Indexing dev would leak the answer
to the very question being asked.
"""
import json
import sys
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TRAIN_PATH = Path("data/spider/train_spider.json")
INDEX_DIR = "chroma_db"
COLLECTION = "spider_train"
MODEL = "all-MiniLM-L6-v2"     # small, fast, CPU-friendly

train = json.loads(TRAIN_PATH.read_text())
print(f"==> {len(train)} training examples")

print(f"==> loading embedding model ({MODEL})")
model = SentenceTransformer(MODEL)

questions = [ex["question"] for ex in train]
print("==> embedding questions (a few minutes on CPU)")
embeddings = model.encode(questions, batch_size=64, show_progress_bar=True)

client = chromadb.PersistentClient(path=INDEX_DIR)
# Rebuild from scratch so reruns are idempotent.
try:
    client.delete_collection(COLLECTION)
except Exception:
    pass
collection = client.create_collection(COLLECTION)

print("==> writing to ChromaDB")
BATCH = 1000
for start in range(0, len(train), BATCH):
    chunk = train[start:start + BATCH]
    collection.add(
        ids=[str(start + i) for i in range(len(chunk))],
        embeddings=[e.tolist() for e in embeddings[start:start + BATCH]],
        documents=[ex["question"] for ex in chunk],
        metadatas=[{"sql": ex["query"], "db_id": ex["db_id"]} for ex in chunk],
    )
    print(f"    ...{min(start + BATCH, len(train))}/{len(train)}")

print(f"\n==> indexed {collection.count()} examples in {INDEX_DIR}/")
