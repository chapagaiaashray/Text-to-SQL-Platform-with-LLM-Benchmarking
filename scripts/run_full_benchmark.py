"""Full-dev-set comparison of all four prompt strategies.

Built for a long run (~3,400 API calls, ~45 minutes):
  * Pre-filters gold queries that don't execute on PostgreSQL, so we don't
    spend API calls on questions we can't score anyway (~18% of the dev set).
  * Saves progress continuously and resumes where it left off. If the run
    dies, just run the script again and it picks up.
  * Retries transient API failures with backoff instead of crashing.
"""
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.prompts.strategies import STRATEGIES
from backend.services.scorer import Scorer
from backend.services.sql_executor import SQLExecutor
from backend.services.sql_generator import SQLGenerator
from backend.utils.spider_hardness import eval_hardness
from backend.utils.sql_dialect import normalize_gold_sql
from backend.prompts.strategies import STRATEGIES

N = 1034
SEED = 42
TIERS = ("easy", "medium", "hard", "extra")
SAVE_EVERY = 25
STATE_PATH = Path("benchmarks/results/full_dev_comparison.json")

# ---- Load the sample (seeded, so indices stay stable across resumes) ----
data = json.loads(Path("data/spider/dev.json").read_text())
random.seed(SEED)
sample = random.sample(data, min(N, len(data)))
hardness = [eval_hardness(ex["sql"]) for ex in sample]

# ---- Load or initialize saved state ----
STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
if STATE_PATH.exists():
    state = json.loads(STATE_PATH.read_text())
    print(f"==> resuming from {STATE_PATH}")
else:
    state = {"gold_valid": {}, "runs": {}}


def save_state():
    STATE_PATH.write_text(json.dumps(state))


# ---- Pass 1: which gold queries actually execute? (no API cost) ----
if len(state["gold_valid"]) < len(sample):
    print("==> checking gold queries (database only, no API cost)")
    executor = SQLExecutor()
    for i, ex in enumerate(sample):
        if str(i) in state["gold_valid"]:
            continue
        res = executor.execute(normalize_gold_sql(ex["query"]), ex["db_id"])
        state["gold_valid"][str(i)] = res.success
        if (i + 1) % 100 == 0:
            print(f"    ...{i + 1}/{len(sample)}")
            save_state()
    save_state()

n_valid = sum(1 for v in state["gold_valid"].values() if v)
print(f"==> {n_valid}/{len(sample)} gold queries are valid on PostgreSQL")


# ---- Pass 2: generate + score, per strategy ----
def generate_with_retry(gen, question, db_id, attempts=4):
    """Retry transient API failures rather than losing the whole run."""
    for attempt in range(attempts):
        try:
            return gen.generate(question, db_id)
        except Exception as exc:
            if attempt == attempts - 1:
                raise
            wait = 2 ** attempt
            print(f"    [retry {attempt + 1}] {str(exc).splitlines()[0][:70]} "
                  f"(waiting {wait}s)")
            time.sleep(wait)


scorer = Scorer()

for strat in ("rag_few_shot",):
    state["runs"].setdefault(strat, {})
    done = state["runs"][strat]
    remaining = len(sample) - len(done)
    if remaining == 0:
        print(f"\n>>> {strat}: already complete, skipping")
        continue

    print(f"\n>>> {strat}  ({remaining} questions remaining)")
    gen = SQLGenerator(strategy=strat)

    for i, ex in enumerate(sample):
        key = str(i)
        if key in done:
            continue

        # Skip API calls for questions whose gold query can't be scored.
        if not state["gold_valid"][key]:
            done[key] = {"bucket": "gold_invalid", "cost": 0.0}
            continue

        r = generate_with_retry(gen, ex["question"], ex["db_id"])
        s = scorer.score(r.sql, ex["query"], ex["db_id"])
        bucket = "correct" if s.correct else "incorrect"
        done[key] = {"bucket": bucket, "cost": r.cost_usd}

        if len(done) % SAVE_EVERY == 0:
            save_state()
            scored = [v for v in done.values() if v["bucket"] != "gold_invalid"]
            hits = sum(1 for v in scored if v["bucket"] == "correct")
            pct = 100 * hits / len(scored) if scored else 0
            print(f"    ...{len(done)}/{len(sample)}  running acc {pct:.1f}%")

    save_state()

save_state()

# ---- Summary ----
print("\n" + "=" * 74)
print(f"FULL DEV SET  |  {len(sample)} questions, seed={SEED}")
print("=" * 74)
print(f"{'strategy':<18}{'correct':>9}{'incorrect':>11}{'gold_inv':>10}"
      f"{'accuracy':>16}{'cost':>10}")
print("-" * 74)

summary = {}
for strat, done in state["runs"].items():
    buckets = Counter(v["bucket"] for v in done.values())
    cost = sum(v["cost"] for v in done.values())
    valid = buckets["correct"] + buckets["incorrect"]
    acc = 100 * buckets["correct"] / valid if valid else 0.0
    summary[strat] = (buckets, valid, acc)
    acc_str = f"{buckets['correct']}/{valid} ({acc:.1f}%)"
    print(f"{strat:<18}{buckets['correct']:>9}{buckets['incorrect']:>11}"
          f"{buckets['gold_invalid']:>10}{acc_str:>16}"
          f"{'$' + format(cost, '.2f'):>10}")

print("\n" + "=" * 82)
print("ACCURACY BY OFFICIAL SPIDER HARDNESS")
print("=" * 82)
header = f"{'strategy':<18}"
for tier in TIERS:
    header += f"{tier:>16}"
print(header)
print("-" * 82)

for strat, done in state["runs"].items():
    hc, hv = Counter(), Counter()
    for key, rec in done.items():
        if rec["bucket"] == "gold_invalid":
            continue
        tier = hardness[int(key)]
        hv[tier] += 1
        if rec["bucket"] == "correct":
            hc[tier] += 1
    row = f"{strat:<18}"
    for tier in TIERS:
        cell = (f"{100 * hc[tier] / hv[tier]:.1f}% ({hc[tier]}/{hv[tier]})"
                if hv[tier] else "n/a")
        row += f"{cell:>16}"
    print(row)

print(f"\nResults saved to {STATE_PATH}")