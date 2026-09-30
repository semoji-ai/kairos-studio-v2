"""원고 학습 — 업로드 스테이징과 publish-collect 규칙에 맞춘 raw entry 기록.

형식의 기준은 publish_agent 의 skills/publish-collect/SKILL.md,
references/format-handling.md, shared/references/workspace-schema.md 다.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from datetime import date
from pathlib import Path

from core.doc_convert import SUPPORTED_EXTS, extract_text

MAX_FILE_BYTES = 100 * 1024 * 1024
MIN_CHARS = 200
SPLIT_LINES = 500
_UPLOAD_ID = re.compile(r"[0-9a-f]{12}")
_SERMON_HINT = re.compile(r"(설교|강해|주일|수요|새벽|금요|예배)")


def normalize_body(text: str) -> str:
    text = text.replace("\r\n", "\n").strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.replace("\t", "    ")


def content_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(normalize_body(text).encode("utf-8")).hexdigest()


def workspace_ready(workspace: Path | None) -> str | None:
    if not workspace or not Path(workspace).is_dir():
        return "no_workspace"
    if not (Path(workspace) / "config.yaml").is_file():
        return "no_config"
    return None


def _author_name(workspace: Path) -> str:
    in_author = False
    for line in (workspace / "config.yaml").read_text(encoding="utf-8").splitlines():
        if re.match(r"^author:\s*$", line):
            in_author = True
            continue
        if in_author:
            if line and not line.startswith((" ", "\t")):
                break
            m = re.match(r"^\s+name:\s*(.*?)\s*$", line)
            if m:
                return m.group(1).strip().strip("\"'")
    return ""


def _safe_name(name: str) -> str:
    base = Path(name.replace("\\", "/")).name
    cleaned = re.sub(r"[^0-9A-Za-z가-힣._ -]+", "-", base).strip(" .-")
    return cleaned[:120] or "원고"


def _title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return re.sub(r"^#+\s*", "", line)[:120]
    return fallback


def _front_value(path: Path, key: str) -> str:
    try:
        head = path.read_text(encoding="utf-8").split("---\n")[1]
    except (OSError, IndexError, UnicodeError):
        return ""
    m = re.search(rf"^{key}:\s*\"?(.*?)\"?\s*$", head, re.M)
    return m.group(1) if m else ""


def _existing_hashes(workspace: Path) -> dict[str, str]:
    out = {}
    for p in (workspace / "raw" / "entries").glob("*.md"):
        h = _front_value(p, "content_hash")
        if h:
            out[h] = _front_value(p, "source_id")
    return out


def _staging(workspace: Path, upload_id: str) -> Path:
    if not _UPLOAD_ID.fullmatch(upload_id):
        raise ValueError("잘못된 업로드 id")
    return workspace / "raw" / "sources" / "_staging" / upload_id


def stage_upload(workspace: Path, files: list[tuple[str, bytes]]) -> dict:
    upload_id = uuid.uuid4().hex[:12]
    stage = _staging(workspace, upload_id)
    stage.mkdir(parents=True)
    known = _existing_hashes(workspace)
    items = []
    for original, data in files:
        name = _safe_name(original)
        while (stage / name).exists():
            name = f"{Path(name).stem}-1{Path(name).suffix}"
        item = {"name": name, "title": Path(name).stem, "chars": 0, "preview": "",
                "status": "ok", "reason": "", "duplicate_of": ""}
        items.append(item)
        if Path(name).suffix.lower() not in SUPPORTED_EXTS:
            item.update(status="error", reason="지원하지 않는 형식입니다")
            continue
        if len(data) > MAX_FILE_BYTES:
            item.update(status="error", reason="파일은 100MB 이하여야 합니다")
            continue
        (stage / name).write_bytes(data)
        try:
            text, _ = extract_text(stage / name, stage / f"{name}.work")
        except (RuntimeError, ValueError, OSError) as exc:
            item.update(status="error", reason=str(exc))
            continue
        body = normalize_body(text)
        (stage / f"{name}.md").write_text(body + "\n", encoding="utf-8")
        chars = len(re.sub(r"\s", "", body))
        item.update(title=_title(body, Path(name).stem), chars=chars,
                    preview=body[:160])
        h = content_hash(body)
        if chars < MIN_CHARS:
            item.update(status="empty", reason="글자가 거의 없습니다(스캔 PDF라면 글자 인식이 필요합니다)")
        elif h in known:
            item.update(status="duplicate", reason="이미 학습한 원고입니다",
                        duplicate_of=known[h])
        else:
            known[h] = f"이번 업로드의 {name}"
    (stage / "items.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return {"upload_id": upload_id, "items": items}


def discard_upload(workspace: Path, upload_id: str) -> None:
    stage = _staging(workspace, upload_id)
    if stage.is_dir():
        shutil.rmtree(stage)


def _split(body: str) -> list[tuple[str, str]]:
    lines = body.split("\n")
    if len(lines) <= SPLIT_LINES:
        return [("", body)]
    parts: list[tuple[str, list[str]]] = []
    cur_title, cur = "", []
    for line in lines:
        at_heading = line.startswith("#") and len(cur) >= 50
        if at_heading or len(cur) >= SPLIT_LINES:
            parts.append((cur_title, cur))
            cur_title, cur = "", []
        if line.startswith("#") and not cur:
            cur_title = re.sub(r"^#+\s*", "", line).strip()[:80]
        cur.append(line)
    if cur:
        parts.append((cur_title, cur))
    return [(t, "\n".join(ls).strip()) for t, ls in parts if "\n".join(ls).strip()]


def _next_number(workspace: Path, day: str) -> int:
    nums = [int(m.group(1)) for p in (workspace / "raw" / "entries").glob(f"{day}_src_{day}_*.md")
            if (m := re.search(r"_(\d{3})\.md$", p.name))]
    return max(nums, default=0) + 1


def _category(title: str, body: str, kind: str) -> str:
    if kind == "reference":
        return "article"
    return "sermon" if _SERMON_HINT.search(title + body[:400]) else "essay"


def _q(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def commit_upload(workspace: Path, upload_id: str, choices: list[dict],
                  today: date | None = None) -> dict:
    stage = _staging(workspace, upload_id)
    items = {i["name"]: i for i in json.loads((stage / "items.json").read_text(encoding="utf-8"))}
    day = (today or date.today()).strftime("%Y%m%d")
    iso = (today or date.today()).isoformat()
    batch_id = f"batch_{day}"
    author = _author_name(workspace)
    entries = workspace / "raw" / "entries"
    sources = workspace / "raw" / "sources" / day
    sources.mkdir(parents=True, exist_ok=True)
    n = _next_number(workspace, day)
    written, counts = [], {"primary": 0, "reference": 0}
    for choice in choices:
        item = items.get(choice.get("name", ""))
        if not item or item["status"] != "ok" or not choice.get("include"):
            continue
        kind = "reference" if choice.get("type") == "reference" else "primary"
        title = (choice.get("title") or item["title"]).strip()[:120]
        body = (stage / f"{item['name']}.md").read_text(encoding="utf-8").strip()
        src_target = sources / item["name"]
        shutil.move(str(stage / item["name"]), src_target)
        rel_source = src_target.relative_to(workspace).as_posix()
        confidence = "high" if Path(item["name"]).suffix.lower() in {".docx", ".md", ".markdown", ".txt"} else "medium"
        parts = _split(body)
        parent = f"src_{day}_{n:03d}" if len(parts) > 1 else ""
        for idx, (part_title, part_body) in enumerate(parts, 1):
            source_id = f"src_{day}_{n:03d}"
            n += 1
            front = [
                "---",
                f"source_id: {source_id}",
                f"batch_id: {batch_id}",
                f"type: {kind}",
                f"category: {_category(title, part_body, kind)}",
                f"title: {_q(title)}",
                f"author: {_q(author if kind == 'primary' else '')}",
                'source_url: ""',
                f"source_path: {_q(rel_source)}",
                f"ingested_at: {iso}",
                f"confidence: {confidence}",
                f"content_hash: {_q(content_hash(part_body))}",
                "tags: []",
                "absorbed: false",
                "deleted: false",
                f"parent_source_id: {_q(parent)}",
                f"part: {idx if parent else 0}",
                f"total_parts: {len(parts) if parent else 0}",
                f"part_title: {_q(part_title if parent else '')}",
                "---",
                "",
            ]
            (entries / f"{day}_{source_id}.md").write_text(
                "\n".join(front) + part_body + "\n", encoding="utf-8")
            written.append(source_id)
        counts[kind] += 1
    discard_upload(workspace, upload_id)
    return {"batch_id": batch_id, "source_ids": written, **counts}
