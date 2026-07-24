"""Real-Spider benchmark over the loaded dev databases.

Samples questions across all loaded databases (not just the first N, which
would all come from one db). Buckets each result into:
  - correct       : generated query matches gold
  - incorrect     : both ran, results differ (a real model miss)
  - gold_invalid  : the gold query itself failed to execute (Spider's gold was
                    written for SQLite; some queries are malformed on Postgres)

Accuracy is reported over the *valid* set (excluding gold_invalid), since a
broken gold query can't fairly count against the model, and is broken down by
Spider's official hardness tiers so results line up with published numbers.
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

# Databases that did not load cleanly. Empty now that type inference is fixed.
SKIP_DBS = set()

N = 100                    # total questions to sample
STRATEGY = "schema_aware"
SEED = 42                  # fixed seed = reproducible sample
TIERS = ("easy", "medium", "hard", "extra")

data = json.loads(Path("data/spider/dev.json").read_text())
data = [ex for ex in data if ex["db_id"] not in SKIP_DBS]

# Sample across the whole dev set so we hit many databases, not just one.
random.seed(SEED)
sample = random.sample(data, min(N, len(data)))

gen = SQLGenerator(strategy=STRATEGY)
scorer = Scorer()

buckets = Counter()
hard_correct = Counter()      # correct, per hardness tier
hard_valid = Counter()        # correct + incorrect, per hardness tier
cost = 0.0
incorrect_examples = []
gold_invalid_examples = []
dbs_hit = set()

for i, ex in enumerate(sample, 1):
    q, gold, db = ex["question"], ex["query"], ex["db_id"]
    dbs_hit.add(db)
    r = gen.generate(q, db)
    s = scorer.score(r.sql, gold, db)
    cost += r.cost_usd

    if s.correct:
        bucket = "correct"
    elif s.reason.startswith("gold query failed"):
        bucket = "gold_invalid"
        gold_invalid_examples.append((db, q, gold, s.reason))
    else:
        bucket = "incorrect"
        incorrect_examples.append((db, q, r.sql, gold, s.reason))
    buckets[bucket] += 1

    # Track per-tier accuracy over valid questions only.
    if bucket in ("correct", "incorrect"):
        tier = eval_hardness(ex["sql"])
        hard_valid[tier] += 1
        if bucket == "correct":
            hard_correct[tier] += 1

    if i % 10 == 0:
        print(f"  ...{i}/{len(sample)} done")

n = len(sample)
valid = buckets["correct"] + buckets["incorrect"]     # exclude gold_invalid
acc_valid = 100 * buckets["correct"] / valid if valid else 0

print("\n" + "=" * 50)
print(f"Strategy: {STRATEGY}   |   {n} questions across {len(dbs_hit)} databases")
print("=" * 50)
print(f"  correct ......... {buckets['correct']}")
print(f"  incorrect ....... {buckets['incorrect']}")
print(f"  gold_invalid .... {buckets['gold_invalid']}  (broken gold SQL, excluded)")
print(f"\n  Accuracy (valid only): {buckets['correct']}/{valid} ({acc_valid:.1f}%)")
print(f"  Total cost: ${cost:.4f}")

print("\n--- accuracy by official Spider hardness ---")
for tier in TIERS:
    total = hard_valid[tier]
    if total:
        pct = 100 * hard_correct[tier] / total
        print(f"  {tier:<8}{hard_correct[tier]:>3}/{total:<4}({pct:.1f}%)")
    else:
        print(f"  {tier:<8}  no valid questions in sample")

print("\n--- sample INCORRECT (real model misses) ---")
for db, q, gen_sql, gold, reason in incorrect_examples[:5]:
    print(f"\n({db}) {q}")
    print(f"  gen:  {gen_sql}")
    print(f"  gold: {gold}")

print("\n--- sample GOLD_INVALID (broken gold queries) ---")
for db, q, gold, reason in gold_invalid_examples[:3]:
    print(f"\n({db}) {q}")
    print(f"  gold: {gold}")
    print(f"  error: {reason.split(':', 1)[-1].strip()[:80]}")