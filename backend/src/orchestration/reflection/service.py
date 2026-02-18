from __future__ import annotations

from collections import deque
from typing import Any

from backend.src.db.models import ReflectionAction
from backend.src.db.repo import Repository


class ReflectionService:
    def __init__(self, repo: Repository) -> None:
        self._repo = repo

    async def reflect(self, state: dict[str, Any], emit_event) -> dict[str, Any]:
        if not state.get("reflection_needed"):
            return state

        reason = state.get("reflection_reason") or "Reflection requested"
        failure_mode = state.get("failure_mode") or "other"
        action = self._decide_action(failure_mode)

        if action == ReflectionAction.REPLANNED.value:
            self._skip_failed_descendants(state)
            await emit_event(
                run_id=state["run_id"],
                event_type="replanned",
                payload={"reason": reason, "failure_mode": failure_mode},
            )
        elif action == ReflectionAction.ADJUSTED_PARAMETERS.value:
            state["reflection_model_preference"] = "expensive"
        else:
            state["should_finish"] = True
            if state.get("finish_status") not in {"failed", "canceled"}:
                state["finish_status"] = "failed"
                state["finish_reason"] = "reflection_terminated"

        diagnostic = {
            "reason": reason,
            "failure_mode": failure_mode,
            "action_taken": action,
        }
        self._repo.append_run_diagnostic(state["run_id"], diagnostic)

        await emit_event(run_id=state["run_id"], event_type="reflection", payload=diagnostic)

        state["reflection_needed"] = False
        state["reflection_reason"] = None
        state["failure_mode"] = None
        return state

    def _decide_action(self, failure_mode: str) -> str:
        if failure_mode in {"timeout", "budget_risk"}:
            return ReflectionAction.TERMINATED.value
        if failure_mode == "schema_error":
            return ReflectionAction.REPLANNED.value
        if failure_mode == "low_confidence":
            return ReflectionAction.ADJUSTED_PARAMETERS.value
        return ReflectionAction.TERMINATED.value

    def _skip_failed_descendants(self, state: dict[str, Any]) -> None:
        nodes = state["dag"]["nodes"]
        failed_ids = {node["id"] for node in nodes if node["status"] == "failed"}
        if not failed_ids:
            return

        adjacency: dict[str, list[str]] = {}
        for edge in state["dag"].get("edges", []):
            adjacency.setdefault(edge["source"], []).append(edge["target"])

        queue = deque(failed_ids)
        seen = set(failed_ids)
        while queue:
            current = queue.popleft()
            for child in adjacency.get(current, []):
                if child in seen:
                    continue
                seen.add(child)
                queue.append(child)

        for node in nodes:
            if node["id"] in seen and node["status"] == "pending":
                node["status"] = "skipped"
                node["last_error"] = {
                    "code": "execution_error",
                    "message": "Skipped due to upstream failure during replanning",
                    "details": {"upstream": sorted(failed_ids)},
                }
