"""피드백 → LLM 증류 → learned_rules. 파싱 실패 시 저장 0 (날조 방지)."""
from __future__ import annotations

import json
from typing import Callable, Iterator

MAX_FEEDBACK_ITEMS = 30
SNIPPET_LEN = 300

_PROMPT_TMPL = """\
다음은 사용자가 이전 답변에 남긴 교정/비선호 피드백 목록이다.
여기서 사용자의 명시적 선호를 규칙 문장으로 추출하라.
기존 규칙과 중복되지 않는 것만 뽑는다. 각 규칙은 한 문장, 최대 5개.
반드시 JSON 배열만 출력하라. 다른 설명 텍스트를 붙이지 마라.
형식: [{{"rule": "...", "source_ids": [...]}}]

기존 활성 규칙:
{existing_rules}

피드백 목록:
{feedback_items}
"""


def _collect_context(store) -> list[dict]:
    last = store._last_feedback_id()
    rows = store._conn().execute(
        "SELECT id, message_id, kind, payload FROM feedback"
        " WHERE kind IN ('correction','down') AND id > ?"
        " ORDER BY id LIMIT ?",
        (last, MAX_FEEDBACK_ITEMS),
    ).fetchall()

    items = []
    for r in rows:
        row = dict(r)
        msg_row = store._conn().execute(
            "SELECT session_id, content_json FROM messages WHERE id=?",
            (row["message_id"],),
        ).fetchone()
        answer_text = ""
        session_id = None
        if msg_row:
            session_id = msg_row["session_id"]
            content = json.loads(msg_row["content_json"])
            answer_text = " ".join(
                p.get("text", "") for p in content if p.get("type") == "text"
            )
        question_text = ""
        if session_id is not None:
            q_row = store._conn().execute(
                "SELECT content_json FROM messages"
                " WHERE session_id=? AND id < ? AND role='user'"
                " ORDER BY id DESC LIMIT 1",
                (session_id, row["message_id"]),
            ).fetchone()
            if q_row:
                q_content = json.loads(q_row["content_json"])
                question_text = " ".join(
                    p.get("text", "") for p in q_content if p.get("type") == "text"
                )
        items.append({
            "id": row["id"],
            "kind": row["kind"],
            "payload": (row["payload"] or "")[:SNIPPET_LEN],
            "question": question_text[:SNIPPET_LEN],
            "answer": answer_text[:SNIPPET_LEN],
        })
    return items


def _build_prompt(items: list[dict], existing_rules: list[dict]) -> str:
    existing_lines = "\n".join(f"- {r['rule']}" for r in existing_rules) or "(없음)"
    feedback_lines = []
    for it in items:
        feedback_lines.append(
            f"- [id={it['id']}, kind={it['kind']}] 질문: {it['question']!r} "
            f"답변: {it['answer']!r} 교정/메모: {it['payload']!r}"
        )
    return _PROMPT_TMPL.format(
        existing_rules=existing_lines,
        feedback_items="\n".join(feedback_lines),
    )


def _extract_json_array(text: str):
    start = text.find("[")
    if start == -1:
        return None
    decoder = json.JSONDecoder()
    try:
        obj, _end = decoder.raw_decode(text, start)
    except json.JSONDecodeError:
        return None
    return obj


def distill(store, chat_fn: Callable[..., Iterator[dict]], cfg: dict | None = None) -> dict:
    items = _collect_context(store)
    if not items:
        return {"added": [], "skipped": "no new feedback"}

    existing_rules = store.list_rules(active_only=True)
    prompt = _build_prompt(items, existing_rules)

    final_text = ""
    for event in chat_fn(prompt, session_ref=None, cfg=cfg):
        if event.get("type") == "done":
            final_text = event.get("text", "") or ""
        elif event.get("type") == "error":
            return {"added": [], "error": "parse"}

    parsed = _extract_json_array(final_text)
    if not isinstance(parsed, list):
        return {"added": [], "error": "parse"}

    added = []
    for entry in parsed:
        if not isinstance(entry, dict):
            return {"added": [], "error": "parse"}
        rule = entry.get("rule")
        source_ids = entry.get("source_ids")
        if not isinstance(rule, str) or not rule.strip() or not isinstance(source_ids, list):
            return {"added": [], "error": "parse"}
        added.append((rule, source_ids))

    for rule, source_ids in added:
        store.add_rule(rule, source_ids)
    store.mark_distilled()

    return {"added": [r for r, _ in added]}
