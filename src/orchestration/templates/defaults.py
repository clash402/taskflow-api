from __future__ import annotations

from src.orchestration.contracts.models import StepContract


DEFAULT_TEMPLATE_ID = "template.default.v1"


def default_template() -> dict:
    graph = {
        "nodes": [
            {
                "id": "understand_task",
                "name": "Understand Task",
                "description": "Clarify objective, constraints, and success criteria.",
                "depends_on": [],
            },
            {
                "id": "execute_task",
                "name": "Execute Task",
                "description": "Perform core execution work to satisfy the user request.",
                "depends_on": ["understand_task"],
            },
            {
                "id": "synthesize_results",
                "name": "Synthesize Results",
                "description": "Assemble outputs into final response artifacts.",
                "depends_on": ["execute_task"],
            },
        ],
        "edges": [
            {"source": "understand_task", "target": "execute_task"},
            {"source": "execute_task", "target": "synthesize_results"},
        ],
    }
    contracts = {
        "understand_task": StepContract(model_preference="cheap", max_retries=1).model_dump(),
        "execute_task": StepContract(model_preference="default", max_retries=2).model_dump(),
        "synthesize_results": StepContract(
            model_preference="expensive", max_retries=1
        ).model_dump(),
    }
    return {
        "id": DEFAULT_TEMPLATE_ID,
        "name": "Default Taskflow Template",
        "version": "1.0.0",
        "description": "A baseline linear DAG for planning, execution, and synthesis.",
        "graph": graph,
        "contracts": contracts,
    }


def seed_templates() -> list[dict]:
    return [default_template()]
