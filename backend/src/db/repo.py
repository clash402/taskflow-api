from __future__ import annotations

import json
import threading
import uuid
from typing import Any

from backend.src.db.engine import SQLiteEngine
from backend.src.utils.time import utc_now_iso


class Repository:
    def __init__(self, engine: SQLiteEngine) -> None:
        self._engine = engine
        self._lock = threading.Lock()

    def init(self) -> None:
        self._engine.init_db()

    def _json_dump(self, value: Any) -> str:
        return json.dumps(value, separators=(",", ":"), default=str)

    def _json_load(self, value: str | None, default: Any) -> Any:
        if not value:
            return default
        return json.loads(value)

    def _row_dict(self, row: Any) -> dict[str, Any]:
        return {k: row[k] for k in row.keys()}

    # Workflows
    def upsert_workflow_template(self, payload: dict[str, Any]) -> None:
        now = utc_now_iso()
        with self._lock:
            with self._engine.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO workflow_templates (
                        id, name, version, description, graph_json, contracts_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name=excluded.name,
                        version=excluded.version,
                        description=excluded.description,
                        graph_json=excluded.graph_json,
                        contracts_json=excluded.contracts_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        payload["id"],
                        payload["name"],
                        payload["version"],
                        payload["description"],
                        self._json_dump(payload["graph"]),
                        self._json_dump(payload["contracts"]),
                        now,
                        now,
                    ),
                )
                conn.commit()

    def list_workflow_templates(self) -> list[dict[str, Any]]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM workflow_templates ORDER BY updated_at DESC"
            ).fetchall()
        return [self._decode_workflow(row) for row in rows]

    def get_workflow_template(self, template_id: str) -> dict[str, Any] | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_templates WHERE id = ?", (template_id,)
            ).fetchone()
        if not row:
            return None
        return self._decode_workflow(row)

    def _decode_workflow(self, row: Any) -> dict[str, Any]:
        data = self._row_dict(row)
        data["graph"] = self._json_load(data.pop("graph_json"), default={})
        data["contracts"] = self._json_load(data.pop("contracts_json"), default={})
        return data

    # Runs
    def create_run(
        self,
        *,
        run_id: str,
        task: str,
        template_id: str | None,
        constraints: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        created_at = utc_now_iso()
        with self._lock:
            with self._engine.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO runs (
                        id, task, template_id, status, constraints_json, diagnostics_json,
                        created_at, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        task,
                        template_id,
                        "created",
                        self._json_dump(constraints),
                        self._json_dump([]),
                        created_at,
                        self._json_dump(metadata or {}),
                    ),
                )
                conn.commit()

    def list_runs(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._decode_run(row) for row in rows]

    def list_incomplete_runs(self) -> list[dict[str, Any]]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM runs WHERE status IN ('created', 'running') ORDER BY created_at DESC"
            ).fetchall()
        return [self._decode_run(row) for row in rows]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._engine.connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            return None
        return self._decode_run(row)

    def update_run(self, run_id: str, **fields: Any) -> None:
        if not fields:
            return
        updates = []
        values: list[Any] = []
        for key, value in fields.items():
            if key in {"constraints", "dag", "diagnostics", "metadata"}:
                updates.append(f"{key}_json = ?")
                values.append(self._json_dump(value))
            else:
                updates.append(f"{key} = ?")
                values.append(value)
        values.append(run_id)
        query = f"UPDATE runs SET {', '.join(updates)} WHERE id = ?"
        with self._lock:
            with self._engine.connect() as conn:
                conn.execute(query, tuple(values))
                conn.commit()

    def request_cancel_run(self, run_id: str) -> None:
        self.update_run(run_id, cancel_requested=1)

    def clear_cancel_request(self, run_id: str) -> None:
        self.update_run(run_id, cancel_requested=0)

    def increment_run_totals(
        self,
        run_id: str,
        *,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        usd: float,
    ) -> None:
        with self._lock:
            with self._engine.connect() as conn:
                conn.execute(
                    """
                    UPDATE runs SET
                        total_prompt_tokens = total_prompt_tokens + ?,
                        total_completion_tokens = total_completion_tokens + ?,
                        total_tokens = total_tokens + ?,
                        total_usd = total_usd + ?
                    WHERE id = ?
                    """,
                    (prompt_tokens, completion_tokens, total_tokens, usd, run_id),
                )
                conn.commit()

    def append_run_diagnostic(self, run_id: str, diagnostic: dict[str, Any]) -> None:
        run = self.get_run(run_id)
        if not run:
            return
        diagnostics = run.get("diagnostics", [])
        diagnostics.append(diagnostic)
        self.update_run(run_id, diagnostics=diagnostics)

    def _decode_run(self, row: Any) -> dict[str, Any]:
        data = self._row_dict(row)
        data["constraints"] = self._json_load(data.pop("constraints_json"), default={})
        data["dag"] = self._json_load(data.pop("dag_json"), default={})
        data["diagnostics"] = self._json_load(data.pop("diagnostics_json"), default=[])
        data["metadata"] = self._json_load(data.pop("metadata_json"), default={})
        data["cancel_requested"] = bool(data["cancel_requested"])
        return data

    # Steps
    def upsert_step(self, payload: dict[str, Any]) -> None:
        with self._lock:
            with self._engine.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO steps (
                        id, run_id, node_id, status, attempts, max_retries, started_at,
                        ended_at, input_json, output_json, error_json, cost_json, logs_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id, node_id) DO UPDATE SET
                        id=excluded.id,
                        status=excluded.status,
                        attempts=excluded.attempts,
                        max_retries=excluded.max_retries,
                        started_at=excluded.started_at,
                        ended_at=excluded.ended_at,
                        input_json=excluded.input_json,
                        output_json=excluded.output_json,
                        error_json=excluded.error_json,
                        cost_json=excluded.cost_json,
                        logs_json=excluded.logs_json
                    """,
                    (
                        payload.get("id") or str(uuid.uuid4()),
                        payload["run_id"],
                        payload["node_id"],
                        payload["status"],
                        payload.get("attempts", 0),
                        payload.get("max_retries", 0),
                        payload.get("started_at"),
                        payload.get("ended_at"),
                        self._json_dump(payload.get("input", {})),
                        (
                            self._json_dump(payload.get("output"))
                            if payload.get("output") is not None
                            else None
                        ),
                        (
                            self._json_dump(payload.get("error"))
                            if payload.get("error") is not None
                            else None
                        ),
                        (
                            self._json_dump(payload.get("cost"))
                            if payload.get("cost") is not None
                            else None
                        ),
                        self._json_dump(payload.get("logs", [])),
                    ),
                )
                conn.commit()

    def get_step(self, step_id: str) -> dict[str, Any] | None:
        with self._engine.connect() as conn:
            row = conn.execute("SELECT * FROM steps WHERE id = ?", (step_id,)).fetchone()
        if not row:
            return None
        return self._decode_step(row)

    def get_step_by_node(self, run_id: str, node_id: str) -> dict[str, Any] | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                "SELECT * FROM steps WHERE run_id = ? AND node_id = ?", (run_id, node_id)
            ).fetchone()
        if not row:
            return None
        return self._decode_step(row)

    def list_steps(self, run_id: str) -> list[dict[str, Any]]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM steps WHERE run_id = ? ORDER BY started_at", (run_id,)
            ).fetchall()
        return [self._decode_step(row) for row in rows]

    def reset_step(self, run_id: str, step_id: str) -> bool:
        with self._lock:
            with self._engine.connect() as conn:
                cur = conn.execute(
                    """
                    UPDATE steps SET
                        status='pending',
                        attempts=0,
                        started_at=NULL,
                        ended_at=NULL,
                        output_json=NULL,
                        error_json=NULL,
                        cost_json=NULL
                    WHERE run_id=? AND id=?
                    """,
                    (run_id, step_id),
                )
                conn.commit()
                return cur.rowcount > 0

    def reset_failed_steps(self, run_id: str) -> int:
        with self._lock:
            with self._engine.connect() as conn:
                cur = conn.execute(
                    """
                    UPDATE steps SET
                        status='pending',
                        started_at=NULL,
                        ended_at=NULL,
                        output_json=NULL,
                        error_json=NULL,
                        cost_json=NULL
                    WHERE run_id=? AND status='failed'
                    """,
                    (run_id,),
                )
                conn.commit()
                return cur.rowcount

    def _decode_step(self, row: Any) -> dict[str, Any]:
        data = self._row_dict(row)
        data["input"] = self._json_load(data.pop("input_json"), default={})
        data["output"] = self._json_load(data.pop("output_json"), default=None)
        data["error"] = self._json_load(data.pop("error_json"), default=None)
        data["cost"] = self._json_load(data.pop("cost_json"), default=None)
        data["logs"] = self._json_load(data.pop("logs_json"), default=[])
        return data

    # Events
    def create_event(
        self,
        *,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        step_id: str | None = None,
    ) -> dict[str, Any]:
        event = {
            "id": str(uuid.uuid4()),
            "run_id": run_id,
            "step_id": step_id,
            "event_type": event_type,
            "payload": payload,
            "created_at": utc_now_iso(),
        }
        with self._lock:
            with self._engine.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO events (id, run_id, step_id, event_type, payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event["id"],
                        event["run_id"],
                        event["step_id"],
                        event["event_type"],
                        self._json_dump(event["payload"]),
                        event["created_at"],
                    ),
                )
                conn.commit()
        return event

    def list_events(self, run_id: str, after_created_at: str | None = None) -> list[dict[str, Any]]:
        with self._engine.connect() as conn:
            if after_created_at:
                rows = conn.execute(
                    """
                    SELECT * FROM events WHERE run_id=? AND created_at>? ORDER BY created_at, id
                    """,
                    (run_id, after_created_at),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM events WHERE run_id=? ORDER BY created_at, id",
                    (run_id,),
                ).fetchall()
        decoded: list[dict[str, Any]] = []
        for row in rows:
            data = self._row_dict(row)
            data["payload"] = self._json_load(data.pop("payload_json"), default={})
            decoded.append(data)
        return decoded

    # Cost ledger
    def create_cost_entry(
        self,
        *,
        run_id: str,
        step_id: str | None,
        app: str,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        usd: float,
        metadata: dict[str, Any],
    ) -> None:
        with self._lock:
            with self._engine.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO cost_ledger (
                        id, run_id, step_id, app, provider, model, prompt_tokens,
                        completion_tokens, total_tokens, usd, metadata_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        run_id,
                        step_id,
                        app,
                        provider,
                        model,
                        prompt_tokens,
                        completion_tokens,
                        total_tokens,
                        usd,
                        self._json_dump(metadata),
                        utc_now_iso(),
                    ),
                )
                conn.commit()

    def list_cost_entries(self, run_id: str) -> list[dict[str, Any]]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM cost_ledger WHERE run_id=? ORDER BY created_at",
                (run_id,),
            ).fetchall()
        decoded = []
        for row in rows:
            data = self._row_dict(row)
            data["metadata"] = self._json_load(data.pop("metadata_json"), default={})
            decoded.append(data)
        return decoded
