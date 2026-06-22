"""Run a few real questions against the loaded sample databases and print
the generated SQL plus cost. This exercises the full pipeline.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.services.sql_generator import SQLGenerator

gen = SQLGenerator()

questions = [
    ("college_1", "How many students have a GPA above 3.5?"),
    ("college_1", "List each student's name and the titles of the courses they are enrolled in."),
    ("pets_1", "How many pets does each owner have?"),
]

total = 0.0
for schema, q in questions:
    r = gen.generate(q, schema)
    print(f"\n[{schema}] {q}")
    print(f"  SQL:  {r.sql}")
    print(f"  cost: ${r.cost_usd:.6f}  ({r.input_tokens} in / {r.output_tokens} out)")
    total += r.cost_usd

print(f"\nTotal: ${total:.6f}")