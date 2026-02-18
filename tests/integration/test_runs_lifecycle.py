from __future__ import annotations

import asyncio
import time

from src.core.llm.provider import MockLLMProvider


def _wait_for_terminal(client, run_id: str, timeout_s: float = 8.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        response = client.get(f"/runs/{run_id}")
        assert response.status_code == 200
        data = response.json()
        if data["status"] in {"completed", "failed", "canceled"}:
            return data
        time.sleep(0.05)
    raise AssertionError("Run did not reach terminal state before timeout")


def test_create_run_emits_events_and_completes(client_factory) -> None:
    with client_factory("lifecycle.db") as client:
        create_response = client.post(
            "/runs",
            json={
                "task": "Create a transparent execution plan and summarize outcome.",
            },
        )
        assert create_response.status_code == 200
        created = create_response.json()
        run_id = created["id"]

        detail = _wait_for_terminal(client, run_id)
        assert detail["status"] == "completed"
        assert len(detail["steps"]) >= 3
        assert all(step["status"] == "completed" for step in detail["steps"])

        sse_lines: list[str] = []
        with client.stream("GET", f"/runs/{run_id}/events") as stream_response:
            assert stream_response.status_code == 200
            for raw_line in stream_response.iter_lines():
                line = raw_line.decode() if isinstance(raw_line, bytes) else raw_line
                if not line:
                    continue
                sse_lines.append(line)
                if "run_finished" in line:
                    break
                if len(sse_lines) > 100:
                    break

        assert any("run_created" in line for line in sse_lines)
        assert any("step_started" in line for line in sse_lines)
        assert any("run_finished" in line for line in sse_lines)


def test_cancel_run_updates_status_and_stops_execution(client_factory, monkeypatch) -> None:
    original_generate = MockLLMProvider.generate

    async def slow_generate(self, **kwargs):
        await asyncio.sleep(0.2)
        return await original_generate(self, **kwargs)

    monkeypatch.setattr(MockLLMProvider, "generate", slow_generate)

    with client_factory("cancel.db") as client:
        create_response = client.post(
            "/runs", json={"task": "Long running task for cancellation test"}
        )
        assert create_response.status_code == 200
        run_id = create_response.json()["id"]

        cancel_response = client.post(f"/runs/{run_id}/cancel")
        assert cancel_response.status_code == 200

        detail = _wait_for_terminal(client, run_id)
        assert detail["status"] == "canceled"
        assert all(step["status"] != "running" for step in detail["steps"])
