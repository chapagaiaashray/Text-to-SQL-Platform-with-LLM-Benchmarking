"""Run all four prompt strategies over the sample and report per-strategy
execution accuracy and cost — the core comparison the project is built around.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.prompts.strategies import STRATEGIES
from backend.services.scorer import Scorer
from backend.services.sql_generator import SQLGenerator

data = json.loads(Path("data/spider_sample/dev.json").read_text())
scorer = Scorer()
n = len(data)

print(f"{'strategy':<18}{'accuracy':>12}{'cost':>10}")
print("-" * 40)

for name in STRATEGIES:
    gen = SQLGenerator(strategy=name)
    correct = 0
    cost = 0.0
    for ex in data:
        r = gen.generate(ex["question"], ex["db_id"])
        s = scorer.score(r.sql, ex["query"], ex["db_id"])
        correct += s.correct
        cost += r.cost_usd
    pct = 100 * correct / n
    print(f"{name:<18}{f'{correct}/{n} ({pct:.0f}%)':>12}{f'${cost:.4f}':>10}")