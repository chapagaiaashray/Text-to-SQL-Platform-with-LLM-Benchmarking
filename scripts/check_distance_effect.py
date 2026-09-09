"""Does retrieval distance predict whether rag_few_shot got the question right?

Uses the saved per-question results from the full rag run plus locally computed
retrieval distances. If accuracy is flat across distance buckets, a distance
threshold cannot help and we skip the experiment.

Caveat: confounded, since close-match questions may simply be easier. Read a
flat result as decisive and a strong result as suggestive.
"""
import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.services.retriever import ExampleRetriever

STATE = Path("benchmarks/results/full_dev_comparison.json")
SEED = 42
BUCKETS = [(0.0, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 9.9)]

state = json.loads(STATE.read_text())
runs = state["runs"]["rag_few_shot"]

data = json.loads(Path("data/spider/dev.json").read_text())
random.seed(SEED)
sample = random.sample(data, min(1034, len(data)))

retriever = ExampleRetriever(k=1)
correct = Counter()
total = Counter()

for key, rec in runs.items():
    if rec["bucket"] == "gold_invalid":
        continue
    i = int(key)
    d = retriever.retrieve(sample[i]["question"], k=1)[0].distance
    for lo, hi in BUCKETS:
        if lo <= d < hi:
            label = f"{lo:.1f}-{hi:.1f}" if hi < 9 else f"{lo:.1f}+"
            total[label] += 1
            if rec["bucket"] == "correct":
                correct[label] += 1
            break
    if len(total) and sum(total.values()) % 200 == 0:
        print(f"  ...{sum(total.values())} scored")

print("\n" + "=" * 54)
print("rag_few_shot accuracy by top-1 retrieval distance")
print("=" * 54)
print(f"{'distance':<12}{'n':>6}{'accuracy':>14}")
print("-" * 54)
for lo, hi in BUCKETS:
    label = f"{lo:.1f}-{hi:.1f}" if hi < 9 else f"{lo:.1f}+"
    if total[label]:
        print(f"{label:<12}{total[label]:>6}"
              f"{f'{100 * correct[label] / total[label]:.1f}%':>14}")
print(f"\nOverall: {sum(correct.values())}/{sum(total.values())}")