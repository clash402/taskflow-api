from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RunStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELED = "canceled"


class FailureCode(str, Enum):
    TIMEOUT = "timeout"
    BUDGET_EXCEEDED = "budget_exceeded"
    SCHEMA_ERROR = "schema_error"
    TOOL_NOT_ALLOWED = "tool_not_allowed"
    EXECUTION_ERROR = "execution_error"
    CANCELED = "canceled"
    MAX_STEPS_EXCEEDED = "max_steps_exceeded"


class ReflectionFailureMode(str, Enum):
    TIMEOUT = "timeout"
    SCHEMA_ERROR = "schema_error"
    LOW_CONFIDENCE = "low_confidence"
    BUDGET_RISK = "budget_risk"
    OTHER = "other"


class ReflectionAction(str, Enum):
    REPLANNED = "replanned"
    ADJUSTED_PARAMETERS = "adjusted_parameters"
    TERMINATED = "terminated"


class StructuredError(BaseModel):
    code: FailureCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class CostRecord(BaseModel):
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    usd: float


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS workflow_templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    description TEXT NOT NULL,
    graph_json TEXT NOT NULL,
    contracts_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    task TEXT NOT NULL,
    template_id TEXT,
    status TEXT NOT NULL,
    constraints_json TEXT NOT NULL,
    dag_json TEXT,
    diagnostics_json TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT,
    total_prompt_tokens INTEGER NOT NULL DEFAULT 0,
    total_completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    total_usd REAL NOT NULL DEFAULT 0,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS steps (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL,
    max_retries INTEGER NOT NULL,
    started_at TEXT,
    ended_at TEXT,
    input_json TEXT NOT NULL,
    output_json TEXT,
    error_json TEXT,
    cost_json TEXT,
    logs_json TEXT,
    UNIQUE(run_id, node_id),
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    step_id TEXT,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS cost_ledger (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    step_id TEXT,
    app TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,
    usd REAL NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_steps_run_id ON steps(run_id);
CREATE INDEX IF NOT EXISTS idx_events_run_id_created_at ON events(run_id, created_at);
CREATE INDEX IF NOT EXISTS idx_cost_ledger_run_id_created_at ON cost_ledger(run_id, created_at);
"""
