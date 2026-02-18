from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class GenericStepOutput(BaseModel):
    summary: str
    confidence: float = Field(ge=0.0, le=1.0)
    artifacts: dict[str, Any] = Field(default_factory=dict)


class PlannerStepOutput(GenericStepOutput):
    pass


class ExecutorStepOutput(GenericStepOutput):
    pass


class ReflectionStepOutput(BaseModel):
    reason: str
    failure_mode: Literal["timeout", "schema_error", "low_confidence", "budget_risk", "other"]
    action_taken: Literal["replanned", "adjusted_parameters", "terminated"]


class StepContract(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    allowed_tools: list[str] = Field(default_factory=lambda: ["llm.generate"])
    timeout_s: int = 30
    max_retries: int = 2
    model_preference: Literal["cheap", "default", "expensive"] = "default"
    expected_output_schema: dict[str, Any] = Field(default_factory=dict)


def validate_output_with_contract(
    output_model: type[BaseModel], output: dict[str, Any]
) -> tuple[bool, dict[str, Any] | None, str | None]:
    try:
        validated = output_model.model_validate(output)
        return True, validated.model_dump(), None
    except ValidationError as exc:
        return False, None, str(exc)
