from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.src.schemas.events import ReflectionDiagnosticSchema
from backend.src.schemas.workflows import WorkflowGraphSchema


class RunConstraintsSchema(BaseModel):
    budget_usd: float = 2.0
    timeout_s: int = 300
    max_steps: int = 30
    reflection_interval_steps: int = 2


class RunCreateRequest(BaseModel):
    task: str
    template_id: str | None = None
    constraints: RunConstraintsSchema | None = None


class RunRetryRequest(BaseModel):
    step_id: str | None = None


class StepExecutionSchema(BaseModel):
    id: str
    run_id: str
    node_id: str
    status: str
    attempts: int
    max_retries: int
    started_at: str | None = None
    ended_at: str | None = None
    input: dict[str, Any]
    output: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    cost: dict[str, Any] | None = None
    logs: list[dict[str, Any]] = Field(default_factory=list)


class RunTotalsSchema(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    usd: float = 0.0


class RunSummarySchema(BaseModel):
    id: str
    task: str
    template_id: str | None = None
    status: str
    constraints: RunConstraintsSchema
    created_at: str
    started_at: str | None = None
    ended_at: str | None = None
    totals: RunTotalsSchema


class RunDetailSchema(RunSummarySchema):
    graph: WorkflowGraphSchema | None = None
    diagnostics: list[ReflectionDiagnosticSchema] = Field(default_factory=list)
    steps: list[StepExecutionSchema] = Field(default_factory=list)
