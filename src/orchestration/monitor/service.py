from __future__ import annotations

import time
from typing import Any

from src.db.models import RunStatus
from src.db.repo import Repository


class MonitorService:
    def __init__(self, repo: Repository) -> None:
        self._repo = repo

    def evaluate(self, state: dict[str, Any]) -> dict[str, Any]:
        run = self._repo.get_run(state["run_id"])
        if not run:
            state["should_finish"] = True
            state["finish_status"] = RunStatus.FAILED.value
            state["finish_reason"] = "run_missing"
            return state

        constraints = state["constraints"]
        dag_nodes = state["dag"].get("nodes", [])
        statuses = [node["status"] for node in dag_nodes]

        if run.get("cancel_requested"):
            state["should_finish"] = True
            state["finish_status"] = RunStatus.CANCELED.value
            state["finish_reason"] = "cancel_requested"
            return state

        elapsed = int(time.monotonic() - state["run_started_monotonic"])
        if elapsed >= constraints["timeout_s"]:
            state["should_finish"] = True
            state["finish_status"] = RunStatus.FAILED.value
            state["finish_reason"] = "timeout"
            state["reflection_needed"] = True
            state["reflection_reason"] = "Run timeout exceeded"
            state["failure_mode"] = "timeout"
            return state

        if run["total_usd"] >= constraints["budget_usd"]:
            state["should_finish"] = True
            state["finish_status"] = RunStatus.FAILED.value
            state["finish_reason"] = "budget_exceeded"
            state["reflection_needed"] = True
            state["reflection_reason"] = "Budget cap exceeded"
            state["failure_mode"] = "budget_risk"
            return state

        completed = all(status in {"completed", "skipped"} for status in statuses) and bool(
            statuses
        )
        if completed:
            state["should_finish"] = True
            state["finish_status"] = RunStatus.COMPLETED.value
            state["finish_reason"] = "all_steps_completed"
            return state

        if not self._has_runnable_nodes(state["dag"]):
            has_running = any(status == "running" for status in statuses)
            has_pending = any(status == "pending" for status in statuses)
            if has_pending and not has_running:
                state["should_finish"] = True
                state["finish_status"] = RunStatus.FAILED.value
                state["finish_reason"] = "dependency_deadlock"
                state["reflection_needed"] = True
                state["reflection_reason"] = "No runnable steps due to unmet dependencies"
                state["failure_mode"] = state.get("failure_mode") or "other"
                return state

        pending_or_running = any(status in {"pending", "running"} for status in statuses)
        if not pending_or_running and any(status == "failed" for status in statuses):
            state["should_finish"] = True
            state["finish_status"] = RunStatus.FAILED.value
            state["finish_reason"] = "steps_failed"
            state["reflection_needed"] = True
            state["reflection_reason"] = "One or more steps failed"
            state["failure_mode"] = state.get("failure_mode") or "other"
            return state

        if state["step_counter"] >= constraints["max_steps"]:
            state["should_finish"] = True
            state["finish_status"] = RunStatus.FAILED.value
            state["finish_reason"] = "max_steps_exceeded"
            state["reflection_needed"] = True
            state["reflection_reason"] = "Max steps exceeded"
            state["failure_mode"] = "other"
            return state

        interval = constraints.get("reflection_interval_steps", 2)
        if (
            state["step_counter"] > 0
            and state["step_counter"] % interval == 0
            and state["progress_made"]
        ):
            state["reflection_needed"] = True
            state["reflection_reason"] = "Periodic reflection boundary reached"
            state["failure_mode"] = state.get("failure_mode") or "low_confidence"
            state["progress_made"] = False
        return state

    def _has_runnable_nodes(self, dag: dict[str, Any]) -> bool:
        nodes = dag.get("nodes", [])
        node_map = {node["id"]: node for node in nodes}
        for node in nodes:
            if node.get("status") != "pending":
                continue
            deps = node.get("depends_on", [])
            if all(node_map.get(dep, {}).get("status") == "completed" for dep in deps):
                return True
        return False
