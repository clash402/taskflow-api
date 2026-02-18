from __future__ import annotations

from pydantic import BaseModel

from src.core.settings import Settings


class CostEstimate(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    usd: float


class CostEstimator:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def estimate(self, *, model: str, prompt_tokens: int, completion_tokens: int) -> CostEstimate:
        prompt_rate, completion_rate = self._rates_for_model(model)
        usd = ((prompt_tokens / 1000) * prompt_rate) + (
            (completion_tokens / 1000) * completion_rate
        )
        return CostEstimate(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            usd=round(usd, 8),
        )

    def _rates_for_model(self, model: str) -> tuple[float, float]:
        if model == self._settings.llm_cheap_model:
            return (
                self._settings.llm_cheap_prompt_per_1k,
                self._settings.llm_cheap_completion_per_1k,
            )
        if model == self._settings.llm_expensive_model:
            return (
                self._settings.llm_expensive_prompt_per_1k,
                self._settings.llm_expensive_completion_per_1k,
            )
        return (
            self._settings.llm_default_prompt_per_1k,
            self._settings.llm_default_completion_per_1k,
        )
