"""End-to-end: for each sample question, generate SQL, execute it, and score
it against the gold answer. Prints per-question results and overall accuracy.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.services.scorer import Scorer
from backend.services.sql_generator import SQLGenerator

data = json.loads(Path("data/spider_sample/dev.json").read_text())
gen = SQLGenerator()
scorer = Scorer()

correct = 0
total_cost = 0.0
for ex in data:
    schema, question, gold_sql = ex["db_id"], ex["question"], ex["query"]
    result = gen.generate(question, schema)
    score = scorer.score(result.sql, gold_sql, schema)
    total_cost += result.cost_usd

    mark = "PASS" if score.correct else "FAIL"
    print(f"\n[{mark}] ({schema}) {question}")
    print(f"   gen:  {result.sql}")
    print(f"   gold: {gold_sql}")
    if not score.correct:
        print(f"   why:  {score.reason}")
    correct += score.correct

n = len(data)
print(f"\n=== {correct}/{n} correct ({100 * correct / n:.0f}%)  |  total cost ${total_cost:.4f} ===")