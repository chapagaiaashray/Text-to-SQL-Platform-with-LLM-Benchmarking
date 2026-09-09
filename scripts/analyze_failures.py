"""Failure-mode diagnostic.

Of the questions the best strategy gets wrong, how many fail because the SQL
does not execute (a signal production code could detect and retry on) versus
how many execute fine but return the wrong rows (undetectable without gold)?

This determines what the RAG self-correction loop can trigger on.
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

N = 150
SEED = 42
STRATEGY = "schema_aware"

data = json.loads(Path("data/spider/dev.json").read_text())
random.seed(SEED)
sample = random.sample(data, min(N, len(data)))

gen = SQLGenerator(strategy=STRATEGY)
scorer = Scorer()

modes = Counter()
by_tier = Counter()
error_kinds = Counter()
examples = []
cost = 0.0

for i, ex in enumerate(sample, 1):
    r = gen.generate(ex["question"], ex["db_id"])
    s = scorer.score(r.sql, ex["query"], ex["db_id"])
    cost += r.cost_usd

    if s.correct:
        modes["correct"] += 1
    elif s.reason.startswith("gold query failed"):
        modes["gold_invalid"] += 1
    elif s.reason.startswith("generated query failed"):
        modes["execution_error"] += 1
        by_tier[eval_hardness(ex["sql"])] += 1
        # Bucket the Postgres error text so we can see what breaks most.
        err = (s.generated.error or "").lower()
        if "does not exist" in err:
            kind = "unknown column/table"
        elif "syntax error" in err:
            kind = "syntax error"
        elif "group by" in err:
            kind = "GROUP BY violation"
        elif "operator does not exist" in err:
            kind = "type mismatch"
        elif "timeout" in err or "canceling" in err:
            kind = "timeout"
        else:
            kind = "other"
        error_kinds[kind] += 1
        examples.append((ex["db_id"], ex["question"], r.sql, s.generated.error))
    else:
        modes["wrong_result"] += 1
        by_tier[eval_hardness(ex["sql"])] += 1

    if i % 25 == 0:
        print(f"  ...{i}/{len(sample)}")

wrong = modes["execution_error"] + modes["wrong_result"]

print("\n" + "=" * 56)
print(f"FAILURE MODES  |  {STRATEGY}, {len(sample)} questions")
print("=" * 56)
print(f"  correct .............. {modes['correct']}")
print(f"  gold_invalid ......... {modes['gold_invalid']}  (excluded)")
print(f"  execution_error ...... {modes['execution_error']}  <- RAG can trigger on these")
print(f"  wrong_result ......... {modes['wrong_result']}  <- silent, needs gold to detect")

if wrong:
    pct = 100 * modes["execution_error"] / wrong
    print(f"\n  {pct:.1f}% of failures are detectable without the gold answer")

print("\n--- execution errors by kind ---")
for kind, n in error_kinds.most_common():
    print(f"  {kind:<24}{n}")

print("\n--- all failures by hardness tier ---")
for tier in ("easy", "medium", "hard", "extra"):
    print(f"  {tier:<8}{by_tier[tier]}")

print("\n--- sample execution errors ---")
for db, q, sql, err in examples[:5]:
    print(f"\n({db}) {q}")
    print(f"  sql:   {sql[:160]}")
    print(f"  error: {err}")

print(f"\nCost: ${cost:.4f}")