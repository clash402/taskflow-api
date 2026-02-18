from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from backend.src.core.settings import Settings
from backend.src.db.models import RunStatus
from backend.src.db.repo import Repository
from backend.src.orchestration.events.broker import EventBroker
from backend.src.orchestration.executor.service import ExecutorService
from backend.src.orchestration.monitor.service import MonitorService
from backend.src.orchestration.planner.service import PlannerService
from backend.src.orchestration.reflection.service import ReflectionService
from backend.src.utils.time import utc_now_iso

try:
    from langgraph.graph import END, StateGraph

    LANGGRAPH_AVAILABLE = True
except ImportError:
    END = "END"
    LANGGRAPH_AVAILABLE = False

logger = logging.getLogger(__name__)


class FallbackCompiledGraph:
    def __init__(
        self,
        *,
        nodes: dict[str, Callable[[dict[str, Any]], dict[str, Any] | Awaitable[dict[str, Any]]]],
        monitor_router: Callable[[dict[str, Any]], str],
    ) -> None:
        self._nodes = nodes
        self._monitor_router = monitor_router

    async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
        current = "plan"
        while current != END:
            result = self._nodes[current](state)
            if asyncio.iscoroutine(result):
                state = await result
            else:
                state = result

            if current in {"plan", "execute_step", "reflect"}:
                current = "monitor"
                continue
            if current == "monitor":
                route = self._monitor_router(state)
                if route == "finish":
                    current = "finish"
                elif route == "reflect":
                    current = "reflect"
                else:
                    current = "execute_step"
                continue
            if current == "finish":
                current = END

        return state


class TaskflowOrchestrator:
    def __init__(
        self,
        *,
        repo: Repository,
        settings: Settings,
        planner: PlannerService,
        executor: ExecutorService,
        monitor: MonitorService,
        reflection: ReflectionService,
        event_broker: EventBroker,
    ) -> None:
        self._repo = repo
        self._settings = settings
        self._planner = planner
        self._executor = executor
        self._monitor = monitor
        self._reflection = reflection
        self._event_broker = event_broker

        self._graph = self._build_graph()
        self._tasks: dict[str, asyncio.Task] = {}

    async def start_run(self, run_id: str, request_id: str = "system") -> None:
        current_task = self._tasks.get(run_id)
        if current_task and not current_task.done():
            return

        task = asyncio.create_task(self._run_loop(run_id=run_id, request_id=request_id))
        self._tasks[run_id] = task

    async def resume_incomplete_runs(self) -> None:
        runs = self._repo.list_incomplete_runs()
        for run in runs:
            await self.start_run(run["id"], request_id="resume")

    def request_cancel(self, run_id: str) -> None:
        self._repo.request_cancel_run(run_id)

    async def retry_run(self, run_id: str, step_id: str | None, request_id: str) -> bool:
        run = self._repo.get_run(run_id)
        if not run:
            return False

        dag = run.get("dag") or {}
        if step_id:
            reset_ok = self._repo.reset_step(run_id, step_id)
            if not reset_ok:
                return False
            self._reset_node_for_step_retry(dag, step_id)
        else:
            self._repo.reset_failed_steps(run_id)
            self._reset_failed_nodes(dag)

        self._repo.update_run(
            run_id,
            status=RunStatus.RUNNING.value,
            ended_at=None,
            cancel_requested=0,
            dag=dag,
        )
        await self._emit_event(
            run_id=run_id,
            event_type="run_retry_requested",
            payload={"step_id": step_id, "request_id": request_id},
        )
        await self.start_run(run_id=run_id, request_id=request_id)
        return True

    async def _run_loop(self, *, run_id: str, request_id: str) -> None:
        run = self._repo.get_run(run_id)
        if not run:
            return
        if run["status"] in {
            RunStatus.COMPLETED.value,
            RunStatus.FAILED.value,
            RunStatus.CANCELED.value,
        }:
            return

        started_at = run.get("started_at") or utc_now_iso()
        self._repo.update_run(run_id, status=RunStatus.RUNNING.value, started_at=started_at)

        await self._emit_event(
            run_id=run_id,
            event_type="run_started",
            payload={"request_id": request_id, "started_at": started_at},
        )

        state = {
            "run_id": run_id,
            "task": run["task"],
            "template_id": run.get("template_id"),
            "constraints": {
                "budget_usd": run["constraints"].get(
                    "budget_usd", self._settings.default_run_budget_usd
                ),
                "timeout_s": run["constraints"].get(
                    "timeout_s", self._settings.default_run_timeout_s
                ),
                "max_steps": run["constraints"].get(
                    "max_steps", self._settings.default_run_max_steps
                ),
                "reflection_interval_steps": run["constraints"].get(
                    "reflection_interval_steps", self._settings.default_reflection_interval_steps
                ),
            },
            "dag": run.get("dag") or {},
            "step_counter": 0,
            "progress_made": False,
            "reflection_needed": False,
            "reflection_reason": None,
            "reflection_model_preference": None,
            "failure_mode": None,
            "should_finish": False,
            "finish_status": None,
            "finish_reason": None,
            "run_started_monotonic": time.monotonic(),
            "request_id": request_id,
        }

        try:
            await self._graph.ainvoke(state)
        except Exception as exc:  # noqa: BLE001
            logger.exception("run %s failed with unhandled error", run_id)
            self._repo.update_run(
                run_id,
                status=RunStatus.FAILED.value,
                ended_at=utc_now_iso(),
                diagnostics=[
                    {
                        "reason": f"Unhandled orchestrator error: {exc}",
                        "failure_mode": "other",
                        "action_taken": "terminated",
                    }
                ],
            )
            await self._emit_event(
                run_id=run_id,
                event_type="run_finished",
                payload={"status": RunStatus.FAILED.value, "reason": "orchestrator_exception"},
            )
        finally:
            self._tasks.pop(run_id, None)

    def _build_graph(self):
        nodes = {
            "plan": self._plan_node,
            "execute_step": self._execute_step_node,
            "monitor": self._monitor_node,
            "reflect": self._reflect_node,
            "finish": self._finish_node,
        }

        if not LANGGRAPH_AVAILABLE:
            return FallbackCompiledGraph(nodes=nodes, monitor_router=self._route_after_monitor)

        graph = StateGraph(dict)
        graph.add_node("plan", self._plan_node)
        graph.add_node("execute_step", self._execute_step_node)
        graph.add_node("monitor", self._monitor_node)
        graph.add_node("reflect", self._reflect_node)
        graph.add_node("finish", self._finish_node)

        graph.set_entry_point("plan")
        graph.add_edge("plan", "monitor")
        graph.add_edge("execute_step", "monitor")
        graph.add_edge("reflect", "monitor")
        graph.add_conditional_edges(
            "monitor",
            self._route_after_monitor,
            {
                "execute_step": "execute_step",
                "reflect": "reflect",
                "finish": "finish",
            },
        )
        graph.add_edge("finish", END)
        return graph.compile()

    def _route_after_monitor(self, state: dict[str, Any]) -> str:
        if state.get("should_finish"):
            return "finish"
        if state.get("reflection_needed"):
            return "reflect"
        return "execute_step"

    async def _plan_node(self, state: dict[str, Any]) -> dict[str, Any]:
        run = self._repo.get_run(state["run_id"])
        if not run:
            state["should_finish"] = True
            state["finish_status"] = RunStatus.FAILED.value
            state["finish_reason"] = "run_missing"
            return state

        dag = await self._planner.plan(
            run=run,
            emit_event=self._emit_event,
            request_id=state["request_id"],
        )
        state["dag"] = dag
        return state

    async def _execute_step_node(self, state: dict[str, Any]) -> dict[str, Any]:
        return await self._executor.execute_next(
            state,
            emit_event=self._emit_event,
            request_id=state["request_id"],
        )

    async def _monitor_node(self, state: dict[str, Any]) -> dict[str, Any]:
        updated = self._monitor.evaluate(state)
        self._repo.update_run(updated["run_id"], dag=updated["dag"])
        return updated

    async def _reflect_node(self, state: dict[str, Any]) -> dict[str, Any]:
        updated = await self._reflection.reflect(state, emit_event=self._emit_event)
        self._repo.update_run(updated["run_id"], dag=updated["dag"])
        return updated

    async def _finish_node(self, state: dict[str, Any]) -> dict[str, Any]:
        status = state.get("finish_status") or RunStatus.FAILED.value
        reason = state.get("finish_reason") or "unknown"
        if status == RunStatus.CANCELED.value:
            self._mark_open_steps_canceled(state)

        self._repo.update_run(
            state["run_id"],
            status=status,
            ended_at=utc_now_iso(),
            cancel_requested=0,
            dag=state["dag"],
        )
        await self._emit_event(
            run_id=state["run_id"],
            event_type="run_finished",
            payload={"status": status, "reason": reason},
        )
        return state

    async def _emit_event(
        self,
        *,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        step_id: str | None = None,
    ) -> None:
        event = self._repo.create_event(
            run_id=run_id,
            step_id=step_id,
            event_type=event_type,
            payload=payload,
        )
        await self._event_broker.publish(event)

    def _mark_open_steps_canceled(self, state: dict[str, Any]) -> None:
        for node in state["dag"].get("nodes", []):
            if node["status"] in {"pending", "running"}:
                node["status"] = "canceled"
                node["last_error"] = {
                    "code": "canceled",
                    "message": "Canceled by human override",
                    "details": {},
                }

        for step in self._repo.list_steps(state["run_id"]):
            if step["status"] not in {"pending", "running"}:
                continue
            self._repo.upsert_step(
                {
                    "id": step["id"],
                    "run_id": step["run_id"],
                    "node_id": step["node_id"],
                    "status": "canceled",
                    "attempts": step["attempts"],
                    "max_retries": step["max_retries"],
                    "started_at": step["started_at"],
                    "ended_at": utc_now_iso(),
                    "input": step["input"],
                    "output": step["output"],
                    "error": {
                        "code": "canceled",
                        "message": "Canceled by human override",
                        "details": {},
                    },
                    "cost": step["cost"],
                    "logs": step["logs"],
                }
            )

    def _reset_node_for_step_retry(self, dag: dict[str, Any], step_id: str) -> None:
        step = self._repo.get_step(step_id)
        if not step:
            return
        target_node_id = step["node_id"]
        for node in dag.get("nodes", []):
            if node["id"] == target_node_id:
                node["status"] = "pending"
                node["last_error"] = None
                node["last_output"] = None

    def _reset_failed_nodes(self, dag: dict[str, Any]) -> None:
        for node in dag.get("nodes", []):
            if node["status"] == "failed":
                node["status"] = "pending"
                node["last_error"] = None
                node["last_output"] = None
