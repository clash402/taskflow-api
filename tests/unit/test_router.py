from src.core.llm.router import ModelRouter, WorkloadType
from src.core.settings import Settings


def test_model_router_selects_expected_models() -> None:
    settings = Settings(
        LLM_PROVIDER="mock",
        LLM_CHEAP_MODEL="cheap-model",
        LLM_DEFAULT_MODEL="default-model",
        LLM_EXPENSIVE_MODEL="expensive-model",
    )
    router = ModelRouter(settings)

    assert router.for_workload(WorkloadType.PLANNER) == "cheap-model"
    assert router.for_workload(WorkloadType.EXECUTOR) == "default-model"
    assert router.for_workload(WorkloadType.REFLECTION) == "expensive-model"
    assert router.for_step("cheap", WorkloadType.EXECUTOR) == "cheap-model"
