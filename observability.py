"""Agent 与工作流的轻量 SQLite 可观测性记录。"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import config_data as config


class ObservabilityService:
    def __init__(self, database_path: str | Path | None = None):
        self.database_path = Path(database_path or config.observability_database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    run_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    title TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    duration_ms REAL NOT NULL DEFAULT 0,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    duration_ms REAL NOT NULL DEFAULT 0,
                    details TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                """
            )

    def start_run(
        self,
        run_type: str,
        title: str,
        run_id: str | None = None,
    ) -> str:
        run_id = run_id or uuid4().hex
        with self._connection() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO runs
                    (run_id, run_type, status, title, started_at)
                VALUES (?, ?, 'running', ?, ?)
                """,
                (run_id, run_type, title[:120], self._now()),
            )
        return run_id

    def log_event(
        self,
        run_id: str,
        event_type: str,
        name: str,
        status: str = "completed",
        duration_ms: float = 0,
        details: dict | None = None,
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO events
                    (run_id, event_type, name, status, duration_ms, details, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    event_type,
                    name,
                    status,
                    duration_ms,
                    json.dumps(details or {}, ensure_ascii=False),
                    self._now(),
                ),
            )

    def add_usage(self, run_id: str, input_tokens: int, output_tokens: int) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE runs
                SET input_tokens = input_tokens + ?,
                    output_tokens = output_tokens + ?
                WHERE run_id = ?
                """,
                (input_tokens, output_tokens, run_id),
            )

    def finish_run(
        self,
        run_id: str,
        status: str,
        duration_ms: float | None = None,
        error: str = "",
    ) -> None:
        with self._connection() as connection:
            if duration_ms is None:
                row = connection.execute(
                    "SELECT started_at FROM runs WHERE run_id = ?", (run_id,)
                ).fetchone()
                if row:
                    started_at = datetime.strptime(row["started_at"], "%Y-%m-%d %H:%M:%S")
                    duration_ms = (datetime.now() - started_at).total_seconds() * 1000
                else:
                    duration_ms = 0
            connection.execute(
                """
                UPDATE runs
                SET status = ?, ended_at = ?, duration_ms = ?, error = ?
                WHERE run_id = ?
                """,
                (status, self._now(), duration_ms, error[:500], run_id),
            )

    def set_status(self, run_id: str, status: str) -> None:
        with self._connection() as connection:
            connection.execute(
                "UPDATE runs SET status = ? WHERE run_id = ?",
                (status, run_id),
            )

    def get_run(self, run_id: str) -> dict | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_events(self, run_id: str) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM events WHERE run_id = ? ORDER BY id", (run_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def list_runs(self, run_type: str | None = None, limit: int = 20) -> list[dict]:
        sql = "SELECT * FROM runs"
        params: list = []
        if run_type:
            sql += " WHERE run_type = ?"
            params.append(run_type)
        sql += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        with self._connection() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def clear_all(self) -> tuple[int, int]:
        """删除全部运行及事件记录，并返回删除数量。"""
        with self._connection() as connection:
            run_count = connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
            event_count = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            connection.execute("DELETE FROM events")
            connection.execute("DELETE FROM runs")
        return run_count, event_count

    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
