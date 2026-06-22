"""LLM router. Sends a prompt to Claude and returns the generated text
along with token usage and an estimated USD cost.

Starts with Claude (economical default: Haiku 4.5). Structured so other
providers (Gemini, Ollama) can be added as new methods later.
"""
from __future__ import annotations

from dataclasses import dataclass

from anthropic import Anthropic

from backend.config import settings

# Per-million-token rates (USD), current as of June 2026. Should update these if pricing changes.
PRICING = {
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
    "claude-sonnet-4-6":          {"input": 3.00, "output": 15.00},
    "claude-opus-4-8":            {"input": 5.00, "output": 25.00},
}


@dataclass
class LLMResponse:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


class LLMRouter:
    def __init__(self, model: str | None = None):
        self.model = model or settings.llm_model
        self._client = Anthropic(api_key=settings.anthropic_api_key)

    def generate(self, prompt: str, *, system: str | None = None,
                 max_tokens: int | None = None,
                 temperature: float = 0.0) -> LLMResponse:
        """Send a prompt, return the text + token usage + estimated cost.

        temperature=0.0 makes output deterministic — important for
        reproducible benchmarking.
        """
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens or settings.llm_max_tokens,
            temperature=temperature,
            system=system or "",
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        cost = self._estimate_cost(resp.usage.input_tokens, resp.usage.output_tokens)
        return LLMResponse(
            text=text.strip(),
            model=self.model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            cost_usd=cost,
        )

    def _estimate_cost(self, in_tokens: int, out_tokens: int) -> float:
        rates = PRICING.get(self.model)
        if not rates:
            return 0.0
        return (in_tokens / 1e6) * rates["input"] + (out_tokens / 1e6) * rates["output"]