"""How close are the retrieved examples, and does closeness vary by difficulty?

Runs retrieval over dev questions and reports the top-1 distance distribution
per hardness tier. This sets the cutoff for adaptive retrieval: below it, use
the retrieved examples; above it, fall back to schema-only prompting.

No API cost — embedding runs locally.
"""
import json
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.services.retriever import ExampleRetriever
from backend.utils.spider_hardness import eval_hardness

N = 300
SEED = 42
TIERS = ("easy", "medium", "hard", "extra")

data = json.loads(Path("data/spider/dev.json").read_text())
random.seed(SEED)
sample = random.sample(data, min(N, len(data)))

retriever = ExampleRetriever(k=1)
by_tier = defaultdict(list)
all_d = []

for i, ex in enumerate(sample, 1):
    top = retriever.retrieve(ex["question"], k=1)[0]
    by_tier[eval_hardness(ex["sql"])].append(top.distance)
    all_d.append(top.distance)
    if i % 100 == 0:
        print(f"  ...{i}/{len(sample)}")

def pct(vals, p):
    s = sorted(vals)
    return s[min(int(len(s) * p), len(s) - 1)]

print("\n" + "=" * 62)
print(f"TOP-1 RETRIEVAL DISTANCE  |  {len(sample)} dev questions")
print("=" * 62)
print(f"{'tier':<10}{'n':>5}{'median':>10}{'25th':>10}{'75th':>10}")
print("-" * 62)
for t in TIERS:
    d = by_tier[t]
    if d:
        print(f"{t:<10}{len(d):>5}{statistics.median(d):>10.3f}"
              f"{pct(d, 0.25):>10.3f}{pct(d, 0.75):>10.3f}")
print(f"{'ALL':<10}{len(all_d):>5}{statistics.median(all_d):>10.3f}"
      f"{pct(all_d, 0.25):>10.3f}{pct(all_d, 0.75):>10.3f}")

print("\n--- share of questions below each candidate cutoff ---")
for cut in (0.4, 0.5, 0.6, 0.7, 0.8):
    share = 100 * sum(1 for d in all_d if d < cut) / len(all_d)
    per_tier = "  ".join(
        f"{t}:{100 * sum(1 for d in by_tier[t] if d < cut) / len(by_tier[t]):.0f}%"
        for t in TIERS if by_tier[t]
    )
    print(f"  < {cut}:  {share:>5.1f}% overall    {per_tier}")