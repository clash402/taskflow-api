from __future__ import annotations

import asyncio

from src.core.llm.cost import CostEstimator
from src.core.llm.provider import MockLLMProvider
from src.core.llm.router import ModelRouter
from src.core.settings import Settings
from src.db.engine import SQLiteEngine
from src.db.repo import Repository
from src.orchestration.executor.service import ExecutorService


def test_retry_policy_transitions_pending_then_failed(monkeypatch, tmp_path) -> None:
    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    settings = Settings(LLM_PROVIDER="mock", DATABASE_URL=f"sqlite:///{tmp_path / 'retry.db'}")
    repo = Repository(SQLiteEngine(settings))
    repo.init()
    repo.create_run(
        run_id="run-1",
        task="retry test",
        template_id=None,
        constraints={
            "budget_usd": 10.0,
            "timeout_s": 60,
            "max_steps": 20,
            "reflection_interval_steps": 5,
        },
    )

    dag = {
        "nodes": [
            {
                "id": "execute_task",
                "name": "Execute",
                "description": "run",
                "depends_on": [],
                "status": "pending",
            }
        ],
        "edges": [],
        "contracts": {
            "execute_task": {
                "allowed_tools": [],
                "timeout_s": 1,
                "max_retries": 1,
                "model_preference": "default",
                "expected_output_schema": {},
            }
        },
    }
    repo.update_run("run-1", dag=dag)

    executor = ExecutorService(
        repo=repo,
        settings=settings,
        llm_provider=MockLLMProvider(),
        model_router=ModelRouter(settings),
        cost_estimator=CostEstimator(settings),
    )

    async def emit_event(**kwargs):
        del kwargs

    state = {
        "run_id": "run-1",
        "task": "retry test",
        "dag": dag,
        "step_counter": 0,
        "progress_made": False,
        "reflection_needed": False,
        "reflection_reason": None,
        "failure_mode": None,
    }

    asyncio.run(executor.execute_next(state, emit_event=emit_event, request_id="req-1"))
    step = repo.get_step_by_node("run-1", "execute_task")
    assert step is not None
    assert step["status"] == "pending"
    assert step["attempts"] == 1

    asyncio.run(executor.execute_next(state, emit_event=emit_event, request_id="req-1"))
    step = repo.get_step_by_node("run-1", "execute_task")
    assert step is not None
    assert step["status"] == "failed"
    assert step["attempts"] == 2
    assert state["reflection_needed"] is True
