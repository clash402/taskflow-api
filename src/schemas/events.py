from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class ReflectionDiagnosticSchema(BaseModel):
    reason: str
    failure_mode: Literal["timeout", "schema_error", "low_confidence", "budget_risk", "other"]
    action_taken: Literal["replanned", "adjusted_parameters", "terminated"]


class EventSchema(BaseModel):
    id: str
    run_id: str
    step_id: str | None = None
    event_type: str
    payload: dict[str, Any]
    created_at: str
