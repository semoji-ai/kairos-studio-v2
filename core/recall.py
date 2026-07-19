"""가중 회상: bigram FTS 인덱스로 과거 대화·피드백을 검색해 현재 세션에 제공."""
from __future__ import annotations

import json
import re

_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]+")


def bigrams(text: str) -> str:
    """한글·영숫자 시퀀스만 추출해 2자 슬라이딩 창으로 분해, 공백 결합."""
    tokens: list[str] = []
    for seq in _TOKEN_RE.findall(text or ""):
        if len(seq) < 2:
            tokens.append(seq)
        else:
            tokens.extend(seq[i:i + 2] for i in range(len(seq) - 1))
    return " ".join(tokens)


def _normalize_whitespace(text: str) -> str:
    """Collapse all whitespace runs (including newlines) to single spaces."""
    return " ".join(text.split())


def _truncate(text: str, n: int = 400) -> str:
    return text[:n]


def _text_of(content_json: str) -> str:
    content = json.loads(content_json)
    return " ".join(p.get("text", "") for p in content if p.get("type") == "text")


def recall(store, query: str, current_session_id: int, limit: int = 3) -> dict:
    empty = {"snippets": [], "avoid": [], "corrections": []}

    tokens = bigrams(query).split()
    if not tokens:
        return empty

    # Cap to first 64 bigram tokens to prevent unbounded FTS queries
    tokens = tokens[:64]
    match_query = " OR ".join(f'"{t}"' for t in tokens)

    conn = store._conn()
    rows = conn.execute(
        """
        SELECT message_id, session_id, role, bm25(messages_fts) AS rank
        FROM messages_fts
        WHERE messages_fts MATCH ?
        ORDER BY rank
        LIMIT 20
        """,
        (match_query,),
    ).fetchall()

    if not rows:
        return empty

    matched_session_ids: set[int] = set()
    candidate_user_mids: list[tuple[int, int, float]] = []  # (message_id, session_id, rank)

    for r in rows:
        sid = r["session_id"]
        if sid == current_session_id:
            continue
        matched_session_ids.add(sid)
        if r["role"] == "user":
            candidate_user_mids.append((r["message_id"], sid, r["rank"]))

    # bm25() in SQLite is negative-better (more negative = more relevant).
    # Normalize to a positive relevance score: higher = better.
    def relevance(rank: float) -> float:
        return -rank

    pairs = []  # dedup by (session_id, user_message_id)
    seen = set()
    for mid, sid, rank in candidate_user_mids:
        key = (sid, mid)
        if key in seen:
            continue
        seen.add(key)

        q_row = conn.execute(
            "SELECT id, content_json FROM messages WHERE id=?", (mid,)
        ).fetchone()
        if q_row is None:
            continue
        q_text = _normalize_whitespace(_text_of(q_row["content_json"]))

        a_row = conn.execute(
            "SELECT id, content_json FROM messages"
            " WHERE session_id=? AND id>? AND role='assistant'"
            " ORDER BY id LIMIT 1",
            (sid, mid),
        ).fetchone()
        if a_row is None:
            continue
        a_text = _normalize_whitespace(_text_of(a_row["content_json"]))
        a_message_id = a_row["id"]

        fb = store.feedback_for_message(a_message_id)
        kinds = [f["kind"] for f in fb]

        score = relevance(rank)
        if "up" in kinds:
            score *= 1.5

        if "down" in kinds:
            pairs.append({
                "_avoid": True,
                "a_text": _truncate(a_text, 200),
                "score": score,
            })
            continue

        pairs.append({
            "q_text": _truncate(q_text),
            "a_text": _truncate(a_text),
            "date": _created_at(conn, mid),
            "score": score,
            "a_id": a_message_id,
        })

    avoid = [p["a_text"] for p in pairs if p.get("_avoid")][:2]
    snippet_candidates = [p for p in pairs if not p.get("_avoid")]
    snippet_candidates.sort(key=lambda p: (p["score"], p.get("a_id", 0)), reverse=True)
    snippets = snippet_candidates[:limit]

    # corrections: FTS 매칭 세션과 관련된 것 우선, 그다음 최근순으로 채워 최대 3건
    all_corrections = store.list_corrections(limit=50)
    related = [c for c in all_corrections if c["session_id"] in matched_session_ids]
    rest = [c for c in all_corrections if c["session_id"] not in matched_session_ids]
    corrections_pool = related + rest
    corrections = [_normalize_whitespace(c["payload"]) for c in corrections_pool[:3]]

    return {"snippets": snippets, "avoid": avoid, "corrections": corrections}


def _created_at(conn, message_id: int) -> str:
    row = conn.execute(
        "SELECT created_at FROM messages WHERE id=?", (message_id,)
    ).fetchone()
    return row["created_at"] if row else ""
