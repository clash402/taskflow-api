from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StepContractSchema(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    allowed_tools: list[str] = Field(default_factory=lambda: ["llm.generate"])
    timeout_s: int = 30
    max_retries: int = 2
    model_preference: Literal["cheap", "default", "expensive"] = "default"
    expected_output_schema: dict[str, Any] = Field(default_factory=dict)


class WorkflowNodeSchema(BaseModel):
    id: str
    name: str
    description: str
    depends_on: list[str] = Field(default_factory=list)
    status: str | None = None
    last_output: dict[str, Any] | None = None
    last_error: dict[str, Any] | None = None


class WorkflowEdgeSchema(BaseModel):
    source: str
    target: str


class WorkflowGraphSchema(BaseModel):
    nodes: list[WorkflowNodeSchema]
    edges: list[WorkflowEdgeSchema]


class WorkflowTemplateSchema(BaseModel):
    id: str
    name: str
    version: str
    description: str
    graph: WorkflowGraphSchema
    contracts: dict[str, StepContractSchema]
    created_at: str | None = None
    updated_at: str | None = None


class WorkflowTemplateUpsertRequest(BaseModel):
    id: str
    name: str
    version: str
    description: str
    graph: WorkflowGraphSchema
    contracts: dict[str, StepContractSchema]
