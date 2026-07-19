"""SQLite persistence. 학습-친화 스키마: 대화 원본 + 피드백을 전부 보존한다."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  role TEXT NOT NULL,
  content_json TEXT NOT NULL,
  provider TEXT,
  model TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS feedback(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id INTEGER NOT NULL REFERENCES messages(id),
  kind TEXT NOT NULL,
  payload TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
  body, message_id UNINDEXED, session_id UNINDEXED, role UNINDEXED
);
"""

_FEEDBACK_KINDS = {"up", "down", "correction"}


class Store:
    def __init__(self, db_path: str | Path):
        self._path = str(db_path)
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        with self._conn() as c:
            c.executescript(_SCHEMA)
        self._backfill_fts()

    def _backfill_fts(self) -> None:
        from core.recall import bigrams  # local import: avoid import cycle at module load

        with self._conn() as c:
            rows = c.execute(
                "SELECT id, session_id, role, content_json FROM messages"
                " WHERE id NOT IN (SELECT message_id FROM messages_fts)"
            ).fetchall()
            for r in rows:
                content = json.loads(r["content_json"])
                text = " ".join(
                    p.get("text", "") for p in content if p.get("type") == "text"
                )
                c.execute(
                    "INSERT INTO messages_fts(body, message_id, session_id, role)"
                    " VALUES (?,?,?,?)",
                    (bigrams(text), r["id"], r["session_id"], r["role"]),
                )

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._path)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    def create_session(self, title: str) -> int:
        with self._conn() as c:
            cur = c.execute("INSERT INTO sessions(title) VALUES (?)", (title,))
            return cur.lastrowid

    def list_sessions(self) -> list[dict]:
        rows = self._conn().execute(
            "SELECT id, title, created_at FROM sessions ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def add_message(self, session_id: int, role: str, content: list[dict],
                    provider: str | None = None, model: str | None = None) -> int:
        from core.recall import bigrams  # local import: avoid import cycle at module load

        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO messages(session_id, role, content_json, provider, model)"
                " VALUES (?,?,?,?,?)",
                (session_id, role, json.dumps(content, ensure_ascii=False), provider, model),
            )
            message_id = cur.lastrowid
            text = " ".join(
                p.get("text", "") for p in content if p.get("type") == "text"
            )
            c.execute(
                "INSERT INTO messages_fts(body, message_id, session_id, role)"
                " VALUES (?,?,?,?)",
                (bigrams(text), message_id, session_id, role),
            )
            return message_id

    def list_messages(self, session_id: int) -> list[dict]:
        rows = self._conn().execute(
            "SELECT id, session_id, role, content_json, provider, model, created_at"
            " FROM messages WHERE session_id=? ORDER BY id",
            (session_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["content"] = json.loads(d.pop("content_json"))
            out.append(d)
        return out

    def add_feedback(self, message_id: int, kind: str, payload: str = "") -> int:
        if kind not in _FEEDBACK_KINDS:
            raise ValueError(f"unknown feedback kind: {kind}")
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO feedback(message_id, kind, payload) VALUES (?,?,?)",
                (message_id, kind, payload),
            )
            return cur.lastrowid

    def feedback_for_message(self, message_id: int) -> list[dict]:
        rows = self._conn().execute(
            "SELECT id, message_id, kind, payload, created_at FROM feedback"
            " WHERE message_id=? ORDER BY id",
            (message_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_corrections(self, limit: int = 20) -> list[dict]:
        rows = self._conn().execute(
            """
            SELECT f.id, f.message_id, f.payload, f.created_at,
                   m.session_id AS session_id,
                   (SELECT content_json FROM messages
                      WHERE session_id = m.session_id AND id < m.id AND role = 'user'
                      ORDER BY id DESC LIMIT 1) AS q_content_json
            FROM feedback f
            JOIN messages m ON m.id = f.message_id
            WHERE f.kind = 'correction'
            ORDER BY f.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            q_content = json.loads(d.pop("q_content_json")) if d.get("q_content_json") else []
            d["q_text"] = " ".join(
                p.get("text", "") for p in q_content if p.get("type") == "text"
            )
            out.append(d)
        return out
