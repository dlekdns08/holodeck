from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

from ..config import DATA_DIR
from ..world.state import WorldState


class SessionStore:
    """SQLite-backed persistence for WorldState. One row per session_id."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or (DATA_DIR / "holodeck.db")
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._conn() as c:
            # WAL lets readers and writers proceed concurrently, which matters once
            # the SSE turn endpoint is reading state mid-generation while another
            # request might be writing.
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def save(self, state: WorldState) -> None:
        payload = state.model_dump_json()
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO sessions (session_id, state_json) VALUES (?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    state_json = excluded.state_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (state.session_id, payload),
            )

    def load(self, session_id: str) -> Optional[WorldState]:
        with self._conn() as c:
            row = c.execute(
                "SELECT state_json FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        if not row:
            return None
        return WorldState.model_validate(json.loads(row["state_json"]))

    def list_sessions(self) -> list[dict]:
        """Return sessions newest-first with enough metadata to render a picker.

        Decodes state_json so genre + beat count come out without a second roundtrip.
        """
        with self._conn() as c:
            rows = c.execute(
                "SELECT session_id, state_json, updated_at FROM sessions ORDER BY updated_at DESC"
            ).fetchall()
        out: list[dict] = []
        for r in rows:
            try:
                state = json.loads(r["state_json"])
            except (TypeError, ValueError):
                state = {}
            out.append(
                {
                    "session_id": r["session_id"],
                    "genre": state.get("genre", "open"),
                    "beats": len(state.get("beats", [])),
                    "updated_at": r["updated_at"],
                }
            )
        return out
