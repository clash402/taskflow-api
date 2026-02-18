from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator
from contextlib import suppress
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.src.core.settings import Settings
from backend.src.db.repo import Repository
from backend.src.orchestration.events.broker import EventBroker
from backend.src.orchestration.runtime import TaskflowOrchestrator
from backend.src.schemas.events import EventSchema
from backend.src.schemas.runs import (
    RunConstraintsSchema,
    RunCreateRequest,
    RunDetailSchema,
    RunRetryRequest,
    RunSummarySchema,
)
from backend.src.schemas.workflows import WorkflowGraphSchema
from backend.src.utils.deps import get_event_broker, get_orchestrator, get_repo, get_settings

router = APIRouter(prefix="/runs", tags=["runs"])


def _default_constraints(settings: Settings) -> dict[str, Any]:
    return {
        "budget_usd": settings.default_run_budget_usd,
        "timeout_s": settings.default_run_timeout_s,
        "max_steps": settings.default_run_max_steps,
        "reflection_interval_steps": settings.default_reflection_interval_steps,
    }


def _to_summary(run: dict[str, Any], settings: Settings) -> RunSummarySchema:
    constraints = _default_constraints(settings)
    constraints.update(run.get("constraints") or {})
    return RunSummarySchema(
        id=run["id"],
        task=run["task"],
        template_id=run.get("template_id"),
        status=run["status"],
        constraints=RunConstraintsSchema(**constraints),
        created_at=run["created_at"],
        started_at=run.get("started_at"),
        ended_at=run.get("ended_at"),
        totals={
            "prompt_tokens": run.get("total_prompt_tokens", 0),
            "completion_tokens": run.get("total_completion_tokens", 0),
            "total_tokens": run.get("total_tokens", 0),
            "usd": round(float(run.get("total_usd", 0.0)), 8),
        },
    )


def _to_detail(
    run: dict[str, Any], steps: list[dict[str, Any]], settings: Settings
) -> RunDetailSchema:
    summary = _to_summary(run, settings)
    graph = run.get("dag") or None
    graph_payload = None
    if graph and graph.get("nodes"):
        graph_payload = WorkflowGraphSchema(
            nodes=[
                {
                    "id": node["id"],
                    "name": node["name"],
                    "description": node.get("description", ""),
                    "depends_on": node.get("depends_on", []),
                    "status": node.get("status"),
                    "last_output": node.get("last_output"),
                    "last_error": node.get("last_error"),
                }
                for node in graph.get("nodes", [])
            ],
            edges=graph.get("edges", []),
        )

    return RunDetailSchema(
        **summary.model_dump(),
        graph=graph_payload,
        diagnostics=run.get("diagnostics", []),
        steps=steps,
    )


@router.get("", response_model=list[RunSummarySchema])
def list_runs(
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> list[RunSummarySchema]:
    return [_to_summary(run, settings) for run in repo.list_runs()]


@router.post("", response_model=RunSummarySchema)
async def create_run(
    payload: RunCreateRequest,
    request: Request,
    repo: Repository = Depends(get_repo),
    orchestrator: TaskflowOrchestrator = Depends(get_orchestrator),
    broker: EventBroker = Depends(get_event_broker),
    settings: Settings = Depends(get_settings),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> RunSummarySchema:
    if payload.template_id and not repo.get_workflow_template(payload.template_id):
        raise HTTPException(status_code=404, detail="Workflow template not found")

    request_id = x_request_id or str(getattr(request.state, "request_id", str(uuid.uuid4())))
    constraints = _default_constraints(settings)
    if payload.constraints:
        constraints.update(payload.constraints.model_dump(exclude_none=True))

    run_id = str(uuid.uuid4())
    repo.create_run(
        run_id=run_id,
        task=payload.task,
        template_id=payload.template_id,
        constraints=constraints,
        metadata={"request_id": request_id},
    )
    event = repo.create_event(
        run_id=run_id,
        event_type="run_created",
        payload={
            "task": payload.task,
            "template_id": payload.template_id,
            "request_id": request_id,
        },
    )
    await broker.publish(event)
    await orchestrator.start_run(run_id=run_id, request_id=request_id)

    run = repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=500, detail="Run creation failed")
    return _to_summary(run, settings)


@router.get("/{run_id}", response_model=RunDetailSchema)
def get_run(
    run_id: str,
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> RunDetailSchema:
    run = repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    steps = repo.list_steps(run_id)
    return _to_detail(run, steps, settings)


@router.post("/{run_id}/cancel", response_model=RunSummarySchema)
async def cancel_run(
    run_id: str,
    request: Request,
    repo: Repository = Depends(get_repo),
    orchestrator: TaskflowOrchestrator = Depends(get_orchestrator),
    broker: EventBroker = Depends(get_event_broker),
    settings: Settings = Depends(get_settings),
) -> RunSummarySchema:
    run = repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    request_id = str(getattr(request.state, "request_id", str(uuid.uuid4())))
    orchestrator.request_cancel(run_id)
    event = repo.create_event(
        run_id=run_id,
        event_type="cancel_requested",
        payload={"request_id": request_id},
    )
    await broker.publish(event)

    refreshed = repo.get_run(run_id)
    if not refreshed:
        raise HTTPException(status_code=500, detail="Run disappeared after cancel request")
    return _to_summary(refreshed, settings)


@router.post("/{run_id}/retry", response_model=RunSummarySchema)
async def retry_run(
    run_id: str,
    payload: RunRetryRequest,
    request: Request,
    repo: Repository = Depends(get_repo),
    orchestrator: TaskflowOrchestrator = Depends(get_orchestrator),
    settings: Settings = Depends(get_settings),
) -> RunSummarySchema:
    if not repo.get_run(run_id):
        raise HTTPException(status_code=404, detail="Run not found")

    request_id = str(getattr(request.state, "request_id", str(uuid.uuid4())))
    ok = await orchestrator.retry_run(run_id, payload.step_id, request_id=request_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Step not found for retry")

    refreshed = repo.get_run(run_id)
    if not refreshed:
        raise HTTPException(status_code=500, detail="Run disappeared after retry")
    return _to_summary(refreshed, settings)


def _format_sse(event: EventSchema) -> str:
    payload = json.dumps(event.model_dump(), separators=(",", ":"))
    return f"event: {event.event_type}\ndata: {payload}\n\n"


async def _sse_stream(
    *,
    run_id: str,
    repo: Repository,
    broker: EventBroker,
) -> AsyncGenerator[str, None]:
    for event in repo.list_events(run_id):
        yield _format_sse(EventSchema(**event))

    subscriber = broker.subscribe(run_id)
    try:
        while True:
            try:
                event = await asyncio.wait_for(anext(subscriber), timeout=15)
                yield _format_sse(EventSchema(**event))
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
            except StopAsyncIteration:
                break
    finally:
        with suppress(Exception):
            await subscriber.aclose()


@router.get("/{run_id}/events")
async def stream_events(
    run_id: str,
    repo: Repository = Depends(get_repo),
    broker: EventBroker = Depends(get_event_broker),
) -> StreamingResponse:
    if not repo.get_run(run_id):
        raise HTTPException(status_code=404, detail="Run not found")

    return StreamingResponse(
        _sse_stream(run_id=run_id, repo=repo, broker=broker),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
