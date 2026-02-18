from __future__ import annotations

from fastapi import Request

from backend.src.core.settings import Settings
from backend.src.db.repo import Repository
from backend.src.orchestration.events.broker import EventBroker
from backend.src.orchestration.runtime import TaskflowOrchestrator


def get_repo(request: Request) -> Repository:
    return request.app.state.repo


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_orchestrator(request: Request) -> TaskflowOrchestrator:
    return request.app.state.orchestrator


def get_event_broker(request: Request) -> EventBroker:
    return request.app.state.event_broker
