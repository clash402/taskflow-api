from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.src.core.settings import get_settings
from main import app


@pytest.fixture
def client_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def _factory(db_name: str = "taskflow-test.db") -> TestClient:
        db_path = tmp_path / db_name
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        monkeypatch.setenv("LLM_PROVIDER", "mock")
        get_settings.cache_clear()
        return TestClient(app)

    return _factory
