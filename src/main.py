from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from src.core.llm.cost import CostEstimator
from src.core.llm.provider import build_provider
from src.core.llm.router import ModelRouter
from src.core.logging import configure_logging
from src.core.settings import Settings, get_settings
from src.db.engine import SQLiteEngine
from src.db.repo import Repository
from src.orchestration.events.broker import EventBroker
from src.orchestration.executor.service import ExecutorService
from src.orchestration.monitor.service import MonitorService
from src.orchestration.planner.service import PlannerService
from src.orchestration.reflection.service import ReflectionService
from src.orchestration.runtime import TaskflowOrchestrator
from src.orchestration.templates.defaults import seed_templates
from src.routers.health import router as health_router
from src.routers.runs import router as runs_router
from src.routers.workflows import router as workflows_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()

    engine = SQLiteEngine(settings)
    repo = Repository(engine)
    repo.init()

    for template in seed_templates():
        repo.upsert_workflow_template(template)

    model_router = ModelRouter(settings)
    cost_estimator = CostEstimator(settings)
    llm_provider = build_provider(settings)

    event_broker = EventBroker()
    planner = PlannerService(
        repo=repo,
        settings=settings,
        llm_provider=llm_provider,
        model_router=model_router,
        cost_estimator=cost_estimator,
    )
    executor = ExecutorService(
        repo=repo,
        settings=settings,
        llm_provider=llm_provider,
        model_router=model_router,
        cost_estimator=cost_estimator,
    )
    monitor = MonitorService(repo=repo)
    reflection = ReflectionService(repo=repo)
    orchestrator = TaskflowOrchestrator(
        repo=repo,
        settings=settings,
        planner=planner,
        executor=executor,
        monitor=monitor,
        reflection=reflection,
        event_broker=event_broker,
    )

    app.state.settings = settings
    app.state.repo = repo
    app.state.event_broker = event_broker
    app.state.orchestrator = orchestrator

    await orchestrator.resume_incomplete_runs()
    yield


app = FastAPI(title="Taskflow API", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    settings: Settings = get_settings()
    request_id = request.headers.get(settings.request_id_header) or str(uuid.uuid4())
    request.state.request_id = request_id

    response = await call_next(request)
    response.headers[settings.request_id_header] = request_id
    return response


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "taskflow-api", "status": "ok"}


app.include_router(health_router)
app.include_router(workflows_router)
app.include_router(runs_router)
