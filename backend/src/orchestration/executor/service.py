from __future__ import annotations

import asyncio
import uuid
from typing import Any

from backend.src.core.llm.cost import CostEstimator
from backend.src.core.llm.provider import LLMProvider
from backend.src.core.llm.router import ModelRouter, WorkloadType
from backend.src.core.settings import Settings
from backend.src.db.models import FailureCode
from backend.src.db.repo import Repository
from backend.src.orchestration.contracts.models import validate_output_with_contract
from backend.src.orchestration.contracts.registry import get_output_model
from backend.src.utils.time import utc_now_iso


class StepExecutionError(Exception):
    def __init__(
        self, code: FailureCode, message: str, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class ExecutorService:
    def __init__(
        self,
        *,
        repo: Repository,
        settings: Settings,
        llm_provider: LLMProvider,
        model_router: ModelRouter,
        cost_estimator: CostEstimator,
    ) -> None:
        self._repo = repo
        self._settings = settings
        self._llm_provider = llm_provider
        self._model_router = model_router
        self._cost_estimator = cost_estimator

    async def execute_next(
        self, state: dict[str, Any], emit_event, request_id: str
    ) -> dict[str, Any]:
        node = self._next_runnable_node(state["dag"])
        if not node:
            state["progress_made"] = False
            return state

        state["progress_made"] = True
        node_id = node["id"]
        contract = state["dag"].get("contracts", {}).get(node_id, {})
        existing_step = self._repo.get_step_by_node(state["run_id"], node_id)
        step_id = existing_step["id"] if existing_step else str(uuid.uuid4())
        attempts = int(existing_step["attempts"]) + 1 if existing_step else 1
        max_retries = int(contract.get("max_retries", 2))
        started_at = utc_now_iso()

        node["status"] = "running"
        self._repo.update_run(state["run_id"], dag=state["dag"])
        self._repo.upsert_step(
            {
                "id": step_id,
                "run_id": state["run_id"],
                "node_id": node_id,
                "status": "running",
                "attempts": attempts,
                "max_retries": max_retries,
                "started_at": started_at,
                "ended_at": None,
                "input": {
                    "task": state["task"],
                    "node": node,
                    "request_id": request_id,
                },
                "output": None,
                "error": None,
                "cost": None,
                "logs": [],
            }
        )
        await emit_event(
            run_id=state["run_id"],
            step_id=step_id,
            event_type="step_started",
            payload={"node_id": node_id, "attempt": attempts},
        )

        try:
            allowed_tools = contract.get("allowed_tools", ["llm.generate"])
            if "llm.generate" not in allowed_tools:
                raise StepExecutionError(
                    FailureCode.TOOL_NOT_ALLOWED,
                    "Contract does not allow llm.generate",
                    {"allowed_tools": allowed_tools},
                )

            model_preference = state.get("reflection_model_preference") or contract.get(
                "model_preference", "default"
            )
            model = self._model_router.for_step(model_preference, WorkloadType.EXECUTOR)
            timeout_s = int(contract.get("timeout_s", 30))
            prompt = self._build_prompt(state, node)
            llm_response = await asyncio.wait_for(
                self._llm_provider.generate(
                    prompt=prompt,
                    model=model,
                    timeout_s=timeout_s,
                    metadata={
                        "phase": "execute_step",
                        "run_id": state["run_id"],
                        "node_id": node_id,
                        "request_id": request_id,
                    },
                ),
                timeout=timeout_s,
            )

            output = {
                "summary": llm_response.content,
                "confidence": 0.85 if model_preference == "expensive" else 0.7,
                "artifacts": {
                    "model": llm_response.model,
                    "provider": llm_response.provider,
                    "node_id": node_id,
                },
            }
            output_model = get_output_model(node_id)
            is_valid, validated_output, validation_error = validate_output_with_contract(
                output_model=output_model,
                output=output,
            )
            if not is_valid:
                raise StepExecutionError(
                    FailureCode.SCHEMA_ERROR,
                    "Step output schema validation failed",
                    {"validation_error": validation_error},
                )

            ended_at = utc_now_iso()
            cost = self._cost_estimator.estimate(
                model=model,
                prompt_tokens=llm_response.prompt_tokens,
                completion_tokens=llm_response.completion_tokens,
            )
            cost_payload = {
                "provider": llm_response.provider,
                "model": model,
                "prompt_tokens": cost.prompt_tokens,
                "completion_tokens": cost.completion_tokens,
                "total_tokens": cost.total_tokens,
                "usd": cost.usd,
            }
            self._repo.upsert_step(
                {
                    "id": step_id,
                    "run_id": state["run_id"],
                    "node_id": node_id,
                    "status": "completed",
                    "attempts": attempts,
                    "max_retries": max_retries,
                    "started_at": started_at,
                    "ended_at": ended_at,
                    "input": {
                        "task": state["task"],
                        "node": node,
                        "request_id": request_id,
                    },
                    "output": validated_output,
                    "error": None,
                    "cost": cost_payload,
                    "logs": [],
                }
            )
            self._repo.create_cost_entry(
                run_id=state["run_id"],
                step_id=step_id,
                app=self._settings.cost_ledger_app,
                provider=llm_response.provider,
                model=model,
                prompt_tokens=cost.prompt_tokens,
                completion_tokens=cost.completion_tokens,
                total_tokens=cost.total_tokens,
                usd=cost.usd,
                metadata={
                    "phase": "step_execution",
                    "node_id": node_id,
                    "attempt": attempts,
                    "request_id": request_id,
                },
            )
            self._repo.increment_run_totals(
                state["run_id"],
                prompt_tokens=cost.prompt_tokens,
                completion_tokens=cost.completion_tokens,
                total_tokens=cost.total_tokens,
                usd=cost.usd,
            )

            node["status"] = "completed"
            node["last_output"] = validated_output
            node["last_error"] = None
            self._repo.update_run(state["run_id"], dag=state["dag"])
            state["step_counter"] += 1

            await emit_event(
                run_id=state["run_id"],
                step_id=step_id,
                event_type="step_finished",
                payload={"node_id": node_id, "cost": cost_payload},
            )
            return state

        except asyncio.TimeoutError as exc:
            await self._handle_step_error(
                state=state,
                step_id=step_id,
                node=node,
                attempts=attempts,
                max_retries=max_retries,
                started_at=started_at,
                error=StepExecutionError(
                    code=FailureCode.TIMEOUT,
                    message="Step execution timed out",
                    details={"timeout_s": contract.get("timeout_s", 30), "raw_error": str(exc)},
                ),
                emit_event=emit_event,
            )
            return state
        except StepExecutionError as exc:
            await self._handle_step_error(
                state=state,
                step_id=step_id,
                node=node,
                attempts=attempts,
                max_retries=max_retries,
                started_at=started_at,
                error=exc,
                emit_event=emit_event,
            )
            return state
        except Exception as exc:  # noqa: BLE001
            await self._handle_step_error(
                state=state,
                step_id=step_id,
                node=node,
                attempts=attempts,
                max_retries=max_retries,
                started_at=started_at,
                error=StepExecutionError(
                    code=FailureCode.EXECUTION_ERROR,
                    message="Unhandled execution error",
                    details={"raw_error": str(exc)},
                ),
                emit_event=emit_event,
            )
            return state

    async def _handle_step_error(
        self,
        *,
        state: dict[str, Any],
        step_id: str,
        node: dict[str, Any],
        attempts: int,
        max_retries: int,
        started_at: str,
        error: StepExecutionError,
        emit_event,
    ) -> None:
        node_id = node["id"]
        ended_at = utc_now_iso()
        structured_error = {
            "code": error.code.value,
            "message": str(error),
            "details": error.details,
        }
        state["step_counter"] += 1

        if attempts <= max_retries:
            backoff_s = min(2 ** (attempts - 1), 8)
            node["status"] = "pending"
            node["last_error"] = structured_error
            self._repo.upsert_step(
                {
                    "id": step_id,
                    "run_id": state["run_id"],
                    "node_id": node_id,
                    "status": "pending",
                    "attempts": attempts,
                    "max_retries": max_retries,
                    "started_at": started_at,
                    "ended_at": ended_at,
                    "input": {
                        "task": state["task"],
                        "node": node,
                    },
                    "output": None,
                    "error": structured_error,
                    "cost": None,
                    "logs": [],
                }
            )
            self._repo.update_run(state["run_id"], dag=state["dag"])
            await emit_event(
                run_id=state["run_id"],
                step_id=step_id,
                event_type="step_retry_scheduled",
                payload={
                    "node_id": node_id,
                    "attempt": attempts,
                    "max_retries": max_retries,
                    "backoff_s": backoff_s,
                    "error": structured_error,
                },
            )
            await asyncio.sleep(backoff_s)
            return

        node["status"] = "failed"
        node["last_error"] = structured_error
        self._repo.upsert_step(
            {
                "id": step_id,
                "run_id": state["run_id"],
                "node_id": node_id,
                "status": "failed",
                "attempts": attempts,
                "max_retries": max_retries,
                "started_at": started_at,
                "ended_at": ended_at,
                "input": {
                    "task": state["task"],
                    "node": node,
                },
                "output": None,
                "error": structured_error,
                "cost": None,
                "logs": [],
            }
        )
        self._repo.update_run(state["run_id"], dag=state["dag"])
        state["reflection_needed"] = True
        state["reflection_reason"] = f"Step {node_id} failed"
        state["failure_mode"] = self._map_failure_mode(error.code.value)
        await emit_event(
            run_id=state["run_id"],
            step_id=step_id,
            event_type="step_failed",
            payload={"node_id": node_id, "error": structured_error},
        )

    def _next_runnable_node(self, dag: dict[str, Any]) -> dict[str, Any] | None:
        nodes = dag.get("nodes", [])
        node_map = {node["id"]: node for node in nodes}
        for node in nodes:
            if node["status"] != "pending":
                continue
            deps = node.get("depends_on", [])
            if all(node_map.get(dep, {}).get("status") == "completed" for dep in deps):
                return node
        return None

    def _build_prompt(self, state: dict[str, Any], node: dict[str, Any]) -> str:
        completed_outputs = [
            {
                "node_id": candidate["id"],
                "output": candidate.get("last_output"),
            }
            for candidate in state["dag"].get("nodes", [])
            if candidate.get("last_output") is not None
        ]
        return (
            f"Task: {state['task']}\n"
            f"Node: {node['id']}\n"
            f"Description: {node['description']}\n"
            f"Completed upstream outputs: {completed_outputs}"
        )

    def _map_failure_mode(self, code: str) -> str:
        if code == FailureCode.TIMEOUT.value:
            return "timeout"
        if code == FailureCode.SCHEMA_ERROR.value:
            return "schema_error"
        return "other"
