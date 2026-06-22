"""Smoke test: one cheap Claude call. Confirms the API key works and
prints token usage + cost so you can see exactly what a call costs.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.services.llm_router import LLMRouter

router = LLMRouter()  # defaults to Haiku
prompt = (
    "Given a PostgreSQL table student(student_id, name, gpa), write a SQL "
    "query that counts students with a GPA above 3.5. Return only the SQL."
)

resp = router.generate(prompt)
print("--- generated SQL ---")
print(resp.text)
print("--- usage ---")
print(f"model:  {resp.model}")
print(f"tokens: {resp.input_tokens} in / {resp.output_tokens} out")
print(f"cost:   ${resp.cost_usd:.6f}")