"""Adaptive retrieval on the full dev set.

Same as rag_few_shot, but retrieved examples are dropped when the match is not
close enough, falling back to schema-only prompting. Tests whether filtering
out weak retrievals recovers the losses seen in the unfiltered RAG run.
"""
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.services.scorer import Scorer
from backend.services.sql_executor import SQLExecutor
from backend.services.sql_generator import SQLGenerator
from backend.utils.spider_hardness import eval_hardness
from backend.utils.sql_dialect import normalize_gold_sql

N = 1034
SEED = 42
THRESHOLD = 0.6
TIERS = ("easy", "medium", "hard", "extra")
SAVE_EVERY = 25
STATE_PATH = Path("benchmarks/results/adaptive_dev.json")

data = json.loads(Path("data/spider/dev.json").read_text())
random.seed(SEED)
sample = random.sample(data, min(N, len(data)))
hardness = [eval_hardness(ex["sql"]) for ex in sample]

STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
state = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {"gold_valid": {}, "run": {}}
if STATE_PATH.exists():
    print(f"==> resuming from {STATE_PATH}")

def save():
    STATE_PATH.write_text(json.dumps(state))

if len(state["gold_valid"]) < len(sample):
    print("==> checking gold queries (no API cost)")
    ex_runner = SQLExecutor()
    for i, ex in enumerate(sample):
        if str(i) in state["gold_valid"]:
            continue
        state["gold_valid"][str(i)] = ex_runner.execute(
            normalize_gold_sql(ex["query"]), ex["db_id"]).success
        if (i + 1) % 200 == 0:
            save()
    save()

print(f"==> {sum(state['gold_valid'].values())}/{len(sample)} gold queries valid")

gen = SQLGenerator(strategy="rag_adaptive", retrieval_threshold=THRESHOLD)
scorer = Scorer()
done = state["run"]

print(f"\n>>> rag_adaptive (threshold {THRESHOLD})  "
      f"{len(sample) - len(done)} remaining")

for i, ex in enumerate(sample):
    key = str(i)
    if key in done:
        continue
    if not state["gold_valid"][key]:
        done[key] = {"bucket": "gold_invalid", "cost": 0.0}
        continue
    for attempt in range(4):
        try:
            r = gen.generate(ex["question"], ex["db_id"])
            break
        except Exception as exc:
            if attempt == 3:
                raise
            print(f"    [retry] {str(exc).splitlines()[0][:60]}")
            time.sleep(2 ** attempt)
    s = scorer.score(r.sql, ex["query"], ex["db_id"])
    done[key] = {"bucket": "correct" if s.correct else "incorrect", "cost": r.cost_usd}
    if len(done) % SAVE_EVERY == 0:
        save()
        scored = [v for v in done.values() if v["bucket"] != "gold_invalid"]
        hits = sum(1 for v in scored if v["bucket"] == "correct")
        print(f"    ...{len(done)}/{len(sample)}  running acc "
              f"{100 * hits / len(scored):.1f}%")
save()

buckets = Counter(v["bucket"] for v in done.values())
cost = sum(v["cost"] for v in done.values())
valid = buckets["correct"] + buckets["incorrect"]

hc, hv = Counter(), Counter()
for key, rec in done.items():
    if rec["bucket"] == "gold_invalid":
        continue
    t = hardness[int(key)]
    hv[t] += 1
    if rec["bucket"] == "correct":
        hc[t] += 1

print("\n" + "=" * 62)
print(f"ADAPTIVE RETRIEVAL  |  threshold {THRESHOLD}")
print("=" * 62)
print(f"  correct: {buckets['correct']}/{valid} "
      f"({100 * buckets['correct'] / valid:.1f}%)   cost ${cost:.2f}")
print(f"  retrieval used on {gen.retrieval_used} questions, "
      f"skipped on {gen.retrieval_skipped}")
print("\n  by hardness:")
for t in TIERS:
    if hv[t]:
        print(f"    {t:<8}{hc[t]:>4}/{hv[t]:<5}({100 * hc[t] / hv[t]:.1f}%)")

print("\n  baselines (same 884 valid questions):")
print("    rag_few_shot 703 (79.5%)   few_shot 703 (79.5%)   schema_aware 702 (79.4%)")