from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from src.core.settings import Settings
from src.db.models import SCHEMA_SQL


class SQLiteEngine:
    def __init__(self, settings: Settings) -> None:
        self._path = settings.sqlite_path

    @property
    def path(self) -> Path:
        return self._path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self._path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def init_db(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.executescript(SCHEMA_SQL)
            conn.commit()
