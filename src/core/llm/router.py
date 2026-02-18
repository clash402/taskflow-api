from __future__ import annotations

from enum import Enum

from src.core.settings import Settings


class WorkloadType(str, Enum):
    PLANNER = "planner"
    EXECUTOR = "executor"
    REFLECTION = "reflection"
    SYNTHESIS = "synthesis"


class ModelRouter:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def for_workload(self, workload: WorkloadType) -> str:
        if workload == WorkloadType.PLANNER:
            return self._settings.llm_cheap_model
        if workload in {WorkloadType.REFLECTION, WorkloadType.SYNTHESIS}:
            return self._settings.llm_expensive_model
        return self._settings.llm_default_model

    def for_step(self, model_preference: str | None, fallback_workload: WorkloadType) -> str:
        if model_preference == "cheap":
            return self._settings.llm_cheap_model
        if model_preference == "expensive":
            return self._settings.llm_expensive_model
        if model_preference == "default":
            return self._settings.llm_default_model
        return self.for_workload(fallback_workload)
