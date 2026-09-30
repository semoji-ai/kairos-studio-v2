"""SQLite persistence. 학습-친화 스키마: 대화 원본 + 피드백을 전부 보존한다."""
from __future__ import annotations

import json
import re
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
CREATE TABLE IF NOT EXISTS learned_rules(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  rule TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT '',
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS distill_state(
  id INTEGER PRIMARY KEY CHECK(id=1),
  last_feedback_id INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS injected_refs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id INTEGER NOT NULL REFERENCES messages(id),
  reference TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_injected_refs_message ON injected_refs(message_id);
CREATE TABLE IF NOT EXISTS document_revisions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id INTEGER,
  path TEXT NOT NULL,
  version_path TEXT NOT NULL,
  original_excerpt TEXT NOT NULL,
  edited_excerpt TEXT NOT NULL,
  diff TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_FEEDBACK_KINDS = {"up", "down", "correction"}


DIRECTIVE_RE = re.compile(r"(앞으로|항상|늘 |매번|계속|기억해|원칙|하지 ?마|말아|지 ?말고)")


class Store:
    def __init__(self, db_path: str | Path):
        self._path = str(db_path)
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        with self._conn() as c:
            c.executescript(_SCHEMA)
            self._migrate(c)
        self._backfill_fts()

    def _migrate(self, c) -> None:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(learned_rules)")}
        if "pending" not in cols:
            c.execute("ALTER TABLE learned_rules ADD COLUMN pending INTEGER NOT NULL DEFAULT 0")
        cols = {r["name"] for r in c.execute("PRAGMA table_info(distill_state)")}
        if "last_message_id" not in cols:
            c.execute("ALTER TABLE distill_state ADD COLUMN last_message_id INTEGER NOT NULL DEFAULT 0")

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

    def rename_session(self, session_id: int, title: str) -> bool:
        """대화 이름 바꾸기. 앞뒤 공백 제거, 최대 100자. 없는 대화면 False."""
        with self._conn() as c:
            cur = c.execute("UPDATE sessions SET title=? WHERE id=?",
                            (title.strip()[:100], session_id))
            return cur.rowcount > 0

    def delete_session(self, session_id: int) -> bool:
        """세션과 그에 속한 메시지·피드백·FTS 색인을 함께 삭제한다.

        존재하지 않는 세션이면 False. 학습 규칙(learned_rules)은 이미 증류된
        결과물이므로 남긴다.
        """
        with self._conn() as c:
            row = c.execute("SELECT id FROM sessions WHERE id=?",
                            (session_id,)).fetchone()
            if row is None:
                return False
            c.execute("DELETE FROM feedback WHERE message_id IN"
                      " (SELECT id FROM messages WHERE session_id=?)",
                      (session_id,))
            c.execute("DELETE FROM injected_refs WHERE message_id IN"
                      " (SELECT id FROM messages WHERE session_id=?)",
                      (session_id,))
            c.execute("DELETE FROM messages_fts WHERE session_id=?", (session_id,))
            c.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
            c.execute("DELETE FROM sessions WHERE id=?", (session_id,))
            return True

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

    def append_parts(self, message_id: int, parts: list[dict]) -> None:
        """메시지의 content에 파트를 덧붙인다 (아티팩트 파트 등). FTS는 텍스트만
        인덱싱하므로 재색인 불필요."""
        if not parts:
            return
        row = self._conn().execute(
            "SELECT content_json FROM messages WHERE id=?", (message_id,)
        ).fetchone()
        if row is None:
            return
        content = json.loads(row["content_json"])
        content.extend(parts)
        with self._conn() as c:
            c.execute(
                "UPDATE messages SET content_json=? WHERE id=?",
                (json.dumps(content, ensure_ascii=False), message_id),
            )

    def add_feedback(self, message_id: int, kind: str, payload: str = "") -> int:
        if kind not in _FEEDBACK_KINDS:
            raise ValueError(f"unknown feedback kind: {kind}")
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO feedback(message_id, kind, payload) VALUES (?,?,?)",
                (message_id, kind, payload),
            )
            return cur.lastrowid

    def add_document_revision(self, message_id: int | None, result: dict) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO document_revisions"
                " (message_id,path,version_path,original_excerpt,edited_excerpt,diff)"
                " VALUES (?,?,?,?,?,?)",
                (
                    message_id, result["path"], result["version_path"],
                    result["original"][:1200], result["edited"][:1200],
                    result["diff"][:8000],
                ),
            )
            return cur.lastrowid

    def list_document_revisions(self, limit: int = 3) -> list[dict]:
        rows = self._conn().execute(
            "SELECT id,message_id,path,version_path,original_excerpt,edited_excerpt,diff,created_at"
            " FROM document_revisions ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def session_for_message(self, message_id: int) -> dict | None:
        row = self._conn().execute(
            "SELECT s.id,s.title FROM messages m"
            " JOIN sessions s ON s.id=m.session_id WHERE m.id=?",
            (message_id,),
        ).fetchone()
        return dict(row) if row else None

    def feedback_for_message(self, message_id: int) -> list[dict]:
        rows = self._conn().execute(
            "SELECT id, message_id, kind, payload, created_at FROM feedback"
            " WHERE message_id=? ORDER BY id",
            (message_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def record_injected_refs(self, message_id: int, references: list[str]) -> int:
        """이 답변에 주입된 성경 자료의 reference를 기록한다.

        이게 있어야 나중에 그 답변이 받은 up/down 평가를 구절 단위로 되짚을 수
        있다. 기록이 없으면 검색은 영원히 사용자 취향을 배울 수 없다.
        """
        rows = [(message_id, r) for r in dict.fromkeys(references) if r]
        if not rows:
            return 0
        with self._conn() as c:
            c.executemany(
                "INSERT INTO injected_refs(message_id, reference) VALUES (?,?)",
                rows,
            )
        return len(rows)

    def reference_feedback_weights(self) -> dict[str, dict]:
        """{reference: {"up": n, "down": n}} — 평가가 달린 구절만."""
        rows = self._conn().execute(
            """
            SELECT ir.reference AS reference,
                   SUM(CASE WHEN f.kind='up' THEN 1 ELSE 0 END) AS ups,
                   SUM(CASE WHEN f.kind='down' THEN 1 ELSE 0 END) AS downs
            FROM injected_refs ir
            JOIN feedback f ON f.message_id = ir.message_id
            WHERE f.kind IN ('up','down')
            GROUP BY ir.reference
            """
        ).fetchall()
        return {
            r["reference"]: {"up": r["ups"], "down": r["downs"]}
            for r in rows if r["ups"] or r["downs"]
        }

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

    def add_rule(self, rule: str, source_ids: list, pending: bool = False) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO learned_rules(rule, source, active, pending) VALUES (?,?,?,?)",
                (rule, json.dumps(source_ids), 0 if pending else 1, 1 if pending else 0),
            )
            return cur.lastrowid

    def list_rules(self, active_only: bool = True) -> list[dict]:
        sql = "SELECT id, rule, source, active, pending, created_at FROM learned_rules"
        if active_only:
            sql += " WHERE active=1"
        sql += " ORDER BY id DESC"
        out = []
        for r in self._conn().execute(sql).fetchall():
            d = dict(r)
            d["source_ids"] = json.loads(d.pop("source")) if d.get("source") else []
            d["active"] = bool(d["active"])
            d["pending"] = bool(d["pending"])
            out.append(d)
        return out

    def set_rule_active(self, rule_id: int, active: bool) -> None:
        with self._conn() as c:
            if active:
                c.execute("UPDATE learned_rules SET active=1, pending=0 WHERE id=?", (rule_id,))
            else:
                c.execute("UPDATE learned_rules SET active=0 WHERE id=?", (rule_id,))

    def _last_message_id(self) -> int:
        row = self._conn().execute(
            "SELECT last_message_id FROM distill_state WHERE id=1").fetchone()
        return row["last_message_id"] if row else 0

    def directive_messages(self, limit: int = 20) -> list[dict]:
        """마지막 증류 이후 목사님 메시지 중 지속적 선호를 밝힌 것(규칙 후보 재료)."""
        rows = self._conn().execute(
            "SELECT id, content_json FROM messages WHERE role='user' AND id > ? ORDER BY id",
            (self._last_message_id(),),
        ).fetchall()
        out = []
        for r in rows:
            text = " ".join(p.get("text", "") for p in json.loads(r["content_json"])
                            if p.get("type") == "text")
            if DIRECTIVE_RE.search(text):
                out.append({"id": r["id"], "text": text[:300]})
                if len(out) >= limit:
                    break
        return out

    def count_undistilled_directives(self) -> int:
        return len(self.directive_messages(limit=1000))

    def mark_directives_distilled(self, up_to_message_id: int) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO distill_state(id, last_message_id) VALUES (1, ?)"
                " ON CONFLICT(id) DO UPDATE SET last_message_id=excluded.last_message_id",
                (up_to_message_id,),
            )

    def _last_feedback_id(self) -> int:
        row = self._conn().execute(
            "SELECT last_feedback_id FROM distill_state WHERE id=1"
        ).fetchone()
        return row["last_feedback_id"] if row else 0

    def count_undistilled_feedback(self) -> int:
        last = self._last_feedback_id()
        row = self._conn().execute(
            "SELECT COUNT(*) AS n FROM feedback"
            " WHERE kind IN ('correction','down') AND id > ?",
            (last,),
        ).fetchone()
        return row["n"]

    def mark_distilled(self, up_to_id: int | None = None) -> None:
        if up_to_id is None:
            row = self._conn().execute("SELECT MAX(id) AS m FROM feedback").fetchone()
            max_id = row["m"] or 0
        else:
            max_id = up_to_id
        with self._conn() as c:
            c.execute(
                "INSERT INTO distill_state(id, last_feedback_id) VALUES (1, ?)"
                " ON CONFLICT(id) DO UPDATE SET last_feedback_id=excluded.last_feedback_id",
                (max_id,),
            )
