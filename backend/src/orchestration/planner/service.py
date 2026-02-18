from __future__ import annotations

import copy
from typing import Any

from backend.src.core.llm.cost import CostEstimator
from backend.src.core.llm.provider import LLMProvider
from backend.src.core.llm.router import ModelRouter, WorkloadType
from backend.src.core.settings import Settings
from backend.src.db.repo import Repository


class PlannerService:
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

    async def plan(
        self,
        *,
        run: dict[str, Any],
        emit_event,
        request_id: str,
    ) -> dict[str, Any]:
        if run.get("dag") and run["dag"].get("nodes"):
            return run["dag"]

        await emit_event(
            run_id=run["id"],
            event_type="planning_started",
            payload={"task": run["task"], "template_id": run.get("template_id")},
        )

        template = None
        if run.get("template_id"):
            template = self._repo.get_workflow_template(run["template_id"])
        if not template:
            templates = self._repo.list_workflow_templates()
            template = templates[0] if templates else None
        if not template:
            raise RuntimeError("No workflow template available")

        planner_model = self._model_router.for_workload(WorkloadType.PLANNER)
        planning_prompt = (
            "Create explicit execution checkpoints for this task and preserve contract semantics.\n"
            f"Task: {run['task']}\n"
            f"Template: {template['name']}"
        )
        llm_response = await self._llm_provider.generate(
            prompt=planning_prompt,
            model=planner_model,
            timeout_s=20,
            metadata={"phase": "planner", "run_id": run["id"], "request_id": request_id},
        )
        cost = self._cost_estimator.estimate(
            model=planner_model,
            prompt_tokens=llm_response.prompt_tokens,
            completion_tokens=llm_response.completion_tokens,
        )
        self._repo.create_cost_entry(
            run_id=run["id"],
            step_id=None,
            app=self._settings.cost_ledger_app,
            provider=llm_response.provider,
            model=llm_response.model,
            prompt_tokens=cost.prompt_tokens,
            completion_tokens=cost.completion_tokens,
            total_tokens=cost.total_tokens,
            usd=cost.usd,
            metadata={"phase": "planning", "request_id": request_id},
        )
        self._repo.increment_run_totals(
            run["id"],
            prompt_tokens=cost.prompt_tokens,
            completion_tokens=cost.completion_tokens,
            total_tokens=cost.total_tokens,
            usd=cost.usd,
        )

        dag = copy.deepcopy(template["graph"])
        for node in dag["nodes"]:
            node["status"] = "pending"
            node["last_output"] = None
            node["last_error"] = None
        dag["contracts"] = copy.deepcopy(template["contracts"])
        dag["planner_notes"] = llm_response.content
        self._repo.update_run(run["id"], dag=dag)

        await emit_event(
            run_id=run["id"],
            event_type="planning_finished",
            payload={
                "node_count": len(dag["nodes"]),
                "edge_count": len(dag["edges"]),
                "model": llm_response.model,
            },
        )
        return dag
