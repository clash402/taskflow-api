from __future__ import annotations

from pydantic import BaseModel

from backend.src.orchestration.contracts.models import (
    ExecutorStepOutput,
    GenericStepOutput,
    PlannerStepOutput,
)


OUTPUT_MODEL_REGISTRY: dict[str, type[BaseModel]] = {
    "understand_task": PlannerStepOutput,
    "execute_task": ExecutorStepOutput,
    "synthesize_results": GenericStepOutput,
}


def get_output_model(node_id: str) -> type[BaseModel]:
    return OUTPUT_MODEL_REGISTRY.get(node_id, GenericStepOutput)
