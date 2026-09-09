"""Head-to-head: retrieved examples vs generic examples vs no examples.

Runs rag_few_shot, few_shot, and schema_aware over identical questions so the
only variable is what examples (if any) the prompt contains. Reports overall
accuracy and a breakdown by official Spider hardness.
"""
import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.services.scorer import Scorer
from backend.services.sql_generator import SQLGenerator
from backend.utils.spider_hardness import eval_hardness

N = 200
SEED = 42
TIERS = ("easy", "medium", "hard", "extra")
ARMS = ("schema_aware", "few_shot", "rag_few_shot")

data = json.loads(Path("data/spider/dev.json").read_text())
random.seed(SEED)
sample = random.sample(data, min(N, len(data)))
hardness = [eval_hardness(ex["sql"]) for ex in sample]

scorer = Scorer()
results = {}

for arm in ARMS:
    gen = SQLGenerator(strategy=arm)
    buckets = Counter()
    hc, hv = Counter(), Counter()
    cost = 0.0
    print(f"\n>>> {arm}")
    for i, (ex, tier) in enumerate(zip(sample, hardness), 1):
        r = gen.generate(ex["question"], ex["db_id"])
        s = scorer.score(r.sql, ex["query"], ex["db_id"])
        cost += r.cost_usd
        if s.correct:
            bucket = "correct"
        elif s.reason.startswith("gold query failed"):
            bucket = "gold_invalid"
        else:
            bucket = "incorrect"
        buckets[bucket] += 1
        if bucket != "gold_invalid":
            hv[tier] += 1
            if bucket == "correct":
                hc[tier] += 1
        if i % 50 == 0:
            print(f"    ...{i}/{len(sample)}")
    valid = buckets["correct"] + buckets["incorrect"]
    results[arm] = {
        "correct": buckets["correct"],
        "valid": valid,
        "acc": 100 * buckets["correct"] / valid if valid else 0,
        "cost": cost,
        "hc": hc,
        "hv": hv,
    }

print("\n" + "=" * 60)
print(f"RAG COMPARISON  |  {len(sample)} questions, seed={SEED}")
print("=" * 60)
print(f"{'strategy':<16}{'accuracy':>18}{'cost':>10}")
print("-" * 60)
for arm, r in results.items():
    acc_str = f"{r['correct']}/{r['valid']} ({r['acc']:.1f}%)"
    cost_str = "$" + format(r["cost"], ".4f")
    print(f"{arm:<16}{acc_str:>18}{cost_str:>10}")

print("\n" + "=" * 74)
print("BY OFFICIAL SPIDER HARDNESS")
print("=" * 74)
header = f"{'strategy':<16}"
for t in TIERS:
    header += f"{t:>14}"
print(header)
print("-" * 74)
for arm, r in results.items():
    row = f"{arm:<16}"
    for t in TIERS:
        cell = (f"{100 * r['hc'][t] / r['hv'][t]:.1f}% ({r['hc'][t]}/{r['hv'][t]})"
                if r["hv"][t] else "n/a")
        row += f"{cell:>14}"
    print(row)