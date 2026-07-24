"""Compare all four prompt strategies on a real Spider sample.

Runs the SAME sampled questions through each strategy so the comparison is
fair, and buckets each result into correct / incorrect / gold_invalid (so
broken SQLite-dialect gold queries don't distort the numbers). Accuracy is
reported over the valid set (correct + incorrect) per strategy, both overall
and broken down by Spider's official hardness tiers.

Note: gold_invalid depends only on whether the gold query executes, so the
valid set is identical across strategies. That makes the per-tier denominators
comparable, and a mismatch would signal a bug.
"""
import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.prompts.strategies import STRATEGIES
from backend.services.scorer import Scorer
from backend.services.sql_generator import SQLGenerator
from backend.utils.spider_hardness import eval_hardness

N = 100
SEED = 42                       # same seed => same questions for every strategy
TIERS = ("easy", "medium", "hard", "extra")

data = json.loads(Path("data/spider/dev.json").read_text())
random.seed(SEED)
sample = random.sample(data, min(N, len(data)))

# Precompute hardness once; it depends on the gold query, not the strategy.
hardness = [eval_hardness(ex["sql"]) for ex in sample]

scorer = Scorer()
results = {}

for strat in STRATEGIES:
    gen = SQLGenerator(strategy=strat)
    buckets = Counter()
    hard_correct = Counter()
    hard_valid = Counter()
    cost = 0.0
    print(f"\n>>> strategy: {strat}")
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

        if bucket in ("correct", "incorrect"):
            hard_valid[tier] += 1
            if bucket == "correct":
                hard_correct[tier] += 1

        if i % 25 == 0:
            print(f"    ...{i}/{len(sample)}")

    valid = buckets["correct"] + buckets["incorrect"]
    acc = 100 * buckets["correct"] / valid if valid else 0.0
    results[strat] = {
        "correct": buckets["correct"],
        "incorrect": buckets["incorrect"],
        "gold_invalid": buckets["gold_invalid"],
        "valid": valid,
        "accuracy": acc,
        "cost": cost,
        "hard_correct": hard_correct,
        "hard_valid": hard_valid,
    }

# ---- Overall summary ----
print("\n" + "=" * 74)
print(f"STRATEGY COMPARISON  |  {len(sample)} questions, seed={SEED}")
print("=" * 74)
print(f"{'strategy':<18}{'correct':>9}{'incorrect':>11}{'gold_inv':>10}"
      f"{'accuracy':>14}{'cost':>10}")
print("-" * 74)
for strat, r in results.items():
    acc_str = f"{r['correct']}/{r['valid']} ({r['accuracy']:.1f}%)"
    cost_str = "$" + format(r["cost"], ".4f")
    print(f"{strat:<18}{r['correct']:>9}{r['incorrect']:>11}"
          f"{r['gold_invalid']:>10}{acc_str:>14}{cost_str:>10}")

# ---- Accuracy by official Spider hardness ----
print("\n" + "=" * 82)
print("ACCURACY BY OFFICIAL SPIDER HARDNESS")
print("=" * 82)
header = f"{'strategy':<18}"
for tier in TIERS:
    header += f"{tier:>16}"
print(header)
print("-" * 82)
for strat, r in results.items():
    row = f"{strat:<18}"
    for tier in TIERS:
        total = r["hard_valid"][tier]
        if total:
            pct = 100 * r["hard_correct"][tier] / total
            cell = f"{pct:.1f}% ({r['hard_correct'][tier]}/{total})"
        else:
            cell = "n/a"
        row += f"{cell:>16}"
    print(row)

print("\nNote: accuracy is over valid questions (gold_invalid excluded).")
print("gold_invalid = SQLite-dialect gold queries PostgreSQL rejects.")
print("Small per-tier samples: differences under ~8 points are within noise.")