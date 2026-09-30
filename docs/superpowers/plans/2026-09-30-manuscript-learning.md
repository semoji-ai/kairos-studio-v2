# 원고 학습 메뉴 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 목사님이 원고·참고자료 파일(HWP/HWPX/DOCX/PDF/MD/TXT)을 올려 퍼블리시 에이전트 위키와 문체 프로필에 반영하는 '원고 학습' 메뉴, 참고자료 인용 원칙, 대화 지시의 규칙 후보화를 만든다.

**Architecture:** 변환·수집은 파이썬(`core/doc_convert.py`, `core/manuscripts.py`)이 publish-collect 규칙대로 `raw/entries/`에 직접 기록하고, 흡수·프로필은 `core/learning.py`의 백그라운드 작업이 Claude로 `/publish-absorb`·`/publish-profile`을 실행한다. 규칙 후보는 `learned_rules.pending` 컬럼과 확장된 `core/distill.py`로 처리한다.

**Tech Stack:** Python 3.9+ stdlib(sqlite3, zipfile, hashlib), React 19 + Vite, pytest, claude CLI provider, Codex `$imagegen`.

**Spec:** `docs/superpowers/specs/2026-09-30-manuscript-learning-design.md`

## Global Constraints

- Python 코드는 3.9 호환(`from __future__ import annotations` 유지), `core/`는 표준 라이브러리만(PDF만 기존처럼 PyMuPDF/pypdf 선택적).
- 공용 코드에 `C:\...`·`/Users/...` 하드코딩 금지. 경로는 settings/인자로.
- 지원 확장자: `.hwp .hwpx .docx .pdf .md .markdown .txt`. 파일당 100MB, 업로드 합계 200MB.
- raw entry: 파일명 `{YYYYMMDD}_{source_id}.md`, `source_id: src_{YYYYMMDD}_{NNN}`, `batch_id: batch_{YYYYMMDD}`.
- content_hash 정규화: ① `\r\n`→`\n` ② strip ③ 빈 줄 3개 이상→2개 ④ 탭→공백 4 → `sha256:`+hex.
- `empty` 판정: 공백 제외 글자 수 < 200. 500줄 초과 분할, 2000줄 이상은 파트당 최대 500줄.
- 학습 작업만 `claude_permission_mode=acceptEdits`, 전역 설정은 불변.
- 대화 규칙 후보는 `pending=1, active=0`으로 저장, 켜면 `pending=0`.
- 한국어 UI 문구: 한자·가나 금지.
- 이미지 생성은 Codex `$imagegen`(공냥 규격, `check_prompt.mjs` 통과)만.
- 머지 전 3종 체크: `.venv/bin/python -m pytest -q`, `cd src-tauri && cargo test`, `cd app && npm run build`.

## Review Focus

- 같은 업로드 안에 같은 원고를 두 번 올림 → 두 번째는 `duplicate`(같은 업로드 기준). Task 2 테스트로 고정.
- 학습 도중 앱 종료 후 재시작 → 작업이 영원히 '흡수 중'으로 남지 않고 `failed`+재시도 가능. Task 4 테스트로 고정.
- `config.yaml` 은 있는데 `author.name` 이 없음/따옴표 없음 → 저자 빈 문자열로 기록, 예외 없이 진행. Task 2 테스트로 고정.
- 파일명이 한글·공백·`../` 포함 → 안전한 이름으로 보관, 작업 폴더 밖에 쓰지 않음. Task 2 테스트로 고정.
- 같은 날 두 번 학습 → source_id 번호가 이어지고(`_004`부터) batch_id는 재사용. Task 2 테스트로 고정.

---

## File Structure

| 파일 | 책임 |
|---|---|
| `core/doc_convert.py` (신규) | 파일 → 마크다운 텍스트 변환(docx/hwpx/hwp/pdf/md/txt). PPT와 공용 |
| `core/presentations.py` (수정) | 변환 함수를 `doc_convert`에서 가져다 씀. 동작 불변 |
| `core/manuscripts.py` (신규) | 스테이징·판정·raw entry 기록(해시·번호·분할·프론트매터) |
| `core/learning.py` (신규) | 학습 작업 상태·실행(absorb→profile)·중단 복구 |
| `core/store.py` (수정) | `pending`, `last_message_id` 이관, 지시 문장 조회 |
| `core/distill.py` (수정) | 대화 지시 구획 추가, 후보 저장 |
| `core/server.py` (수정) | `/learning/*` 경로, 다중 파일 multipart, 증류 문턱 |
| `app/src/api.ts` (수정) | 학습 API·Rule.pending |
| `app/src/Learning.tsx` (신규) | 원고 학습 화면 |
| `app/src/Chat.tsx`, `Settings.tsx`, `index.css` (수정) | 메뉴·후보 배지·스타일 |
| `app/src/assets/icons/learn.png` (신규) | 도자기 메뉴 타일 |
| `publish_agent/skills/publish-write/SKILL.md`, `publish-sermon/SKILL.md` | 참고자료 인용 원칙 |

---

### Task 1: 공용 문서 변환 모듈

**Files:**
- Create: `core/doc_convert.py`
- Modify: `core/presentations.py` (상단 상수·`_local`·`_write_asset`·`_extract_*`·`_convert_hwp_to_hwpx` 제거 후 import, `normalize_document` 본문을 `extract_text` 호출로)
- Test: `tests/test_doc_convert.py`

**Interfaces:**
- Produces: `SUPPORTED_EXTS: set[str]`, `extract_text(source: Path, work_dir: Path) -> tuple[str, list[dict]]` — 지원 밖 확장자는 `ValueError`, 변환 실패는 `RuntimeError`(한국어 사유).

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_doc_convert.py`

```python
import zipfile

import pytest

from core.doc_convert import SUPPORTED_EXTS, extract_text


def _docx(path, paragraphs):
    body = "".join(
        f'<w:p><w:pPr><w:pStyle w:val="{s}"/></w:pPr><w:r><w:t>{t}</w:t></w:r></w:p>'
        for s, t in paragraphs)
    xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f'<w:body>{body}</w:body></w:document>')
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", xml)


def _hwpx(path, paragraphs):
    ps = "".join(f"<hp:p><hp:run><hp:t>{t}</hp:t></hp:run></hp:p>" for t in paragraphs)
    xml = f'<hs:sec xmlns:hs="urn:hs" xmlns:hp="urn:hp">{ps}</hs:sec>'
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("Contents/section0.xml", xml)


def test_supported_extensions():
    assert SUPPORTED_EXTS == {".pdf", ".docx", ".hwp", ".hwpx", ".md", ".markdown", ".txt"}


def test_docx_headings_and_paragraphs(tmp_path):
    src = tmp_path / "설교.docx"
    _docx(src, [("Heading1", "정죄함이 없는 자유"), ("Normal", "본문 첫 문단")])
    text, assets = extract_text(src, tmp_path / "work")
    assert "# 정죄함이 없는 자유" in text
    assert "본문 첫 문단" in text
    assert assets == []


def test_hwpx_paragraphs(tmp_path):
    src = tmp_path / "설교.hwpx"
    _hwpx(src, ["첫째 문단", "둘째 문단"])
    text, _ = extract_text(src, tmp_path / "work")
    assert "첫째 문단" in text and "둘째 문단" in text


def test_txt_utf8_bom_and_cp949(tmp_path):
    a = tmp_path / "a.txt"
    a.write_bytes("\ufeff은혜".encode("utf-8"))
    b = tmp_path / "b.txt"
    b.write_bytes("말씀".encode("cp949"))
    assert extract_text(a, tmp_path / "w1")[0].strip() == "은혜"
    assert extract_text(b, tmp_path / "w2")[0].strip() == "말씀"


def test_unsupported_extension(tmp_path):
    src = tmp_path / "x.xlsx"
    src.write_bytes(b"x")
    with pytest.raises(ValueError):
        extract_text(src, tmp_path / "work")


def test_hwp_without_converter_raises_runtime_error(tmp_path, monkeypatch):
    import core.doc_convert as dc
    monkeypatch.setattr(dc.shutil, "which", lambda name: None)
    monkeypatch.setattr(dc.os, "name", "posix")
    src = tmp_path / "x.hwp"
    src.write_bytes(b"not really hwp")
    with pytest.raises(RuntimeError, match="HWP"):
        extract_text(src, tmp_path / "work")


def test_pdf_when_library_available(tmp_path):
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Grace alone")
    src = tmp_path / "x.pdf"
    doc.save(src)
    text, _ = extract_text(src, tmp_path / "work")
    assert "Grace alone" in text
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest -q tests/test_doc_convert.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.doc_convert'`

- [ ] **Step 3: 구현** — `core/doc_convert.py` 생성. `core/presentations.py` 의 `_IMAGE_EXTS`, `_local`, `_write_asset`, `_extract_docx`, `_extract_hwpx`, `_convert_hwp_to_hwpx`, `_extract_pdf` 를 **그대로 잘라 옮기고**(내용 수정 없음; `_write_asset`이 쓰는 `hashlib` import 포함), 아래를 추가한다.

```python
"""문서 → 마크다운 텍스트 변환. PPT 제작과 원고 학습이 함께 쓴다."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

SUPPORTED_EXTS = {".pdf", ".docx", ".hwp", ".hwpx", ".md", ".markdown", ".txt"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff",
               ".webp", ".svg", ".emf", ".wmf"}

# ... (_local, _write_asset, _extract_docx, _extract_hwpx,
#      _convert_hwp_to_hwpx, _extract_pdf 를 presentations.py 에서 그대로 이동)


def _read_plain(source: Path) -> str:
    data = source.read_bytes()
    for enc in ("utf-8-sig", "cp949"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def extract_text(source: Path, work_dir: Path) -> tuple[str, list[dict]]:
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_EXTS:
        raise ValueError(f"지원하지 않는 파일 형식입니다: {suffix}")
    work_dir.mkdir(parents=True, exist_ok=True)
    if suffix in {".md", ".markdown", ".txt"}:
        return _read_plain(source), []
    if suffix == ".docx":
        return _extract_docx(source, work_dir)
    if suffix == ".hwpx":
        return _extract_hwpx(source, work_dir)
    if suffix == ".hwp":
        converted = work_dir / (source.stem + ".hwpx")
        if _convert_hwp_to_hwpx(source, converted):
            return _extract_hwpx(converted, work_dir)
        txt = converted.with_suffix(".txt")
        if txt.is_file():
            return txt.read_text(encoding="utf-8"), []
        raise RuntimeError("HWP 변환 실패: 한컴오피스 또는 hwp5txt가 필요합니다")
    return _extract_pdf(source, work_dir)
```

`core/presentations.py` 는 옮긴 정의를 지우고 다음으로 대체한다(`_SUPPORTED`는 PPT용으로 그대로 둔다 — `.txt` 추가하지 않음).

```python
from core.doc_convert import extract_text
```

`normalize_document` 의 분기 블록(`if suffix in {".md", ...}` ~ `text, assets = _extract_pdf(...)`)을 다음 한 줄로 바꾼다.

```python
    text, assets = extract_text(source, out_dir)
```

`hashlib`, `zipfile`, `ElementTree`, `subprocess` import가 presentations.py 의 다른 곳에서 쓰이면 남기고, 아니면 지운다(`.venv/bin/python -m pyflakes` 대신 `grep -n "hashlib\.\|zipfile\.\|ET\.\|subprocess\." core/presentations.py`로 확인).

- [ ] **Step 4: 통과 확인(새 테스트 + PPT 회귀)**

Run: `.venv/bin/python -m pytest -q tests/test_doc_convert.py tests/test_presentations.py`
Expected: PASS (pdf 테스트는 PyMuPDF 없으면 skipped)

- [ ] **Step 5: Commit**

```bash
git add core/doc_convert.py core/presentations.py tests/test_doc_convert.py
git commit -m "문서 변환을 공용 모듈로 분리 — 원고 학습과 PPT가 함께 사용, txt 지원"
```

---

### Task 2: 원고 스테이징·기록 (publish-collect 규칙)

**Files:**
- Create: `core/manuscripts.py`
- Test: `tests/test_manuscripts.py`

**Interfaces:**
- Consumes: `core.doc_convert.extract_text`, `SUPPORTED_EXTS`
- Produces:
  - `normalize_body(text: str) -> str`, `content_hash(text: str) -> str`
  - `workspace_ready(workspace: Path | None) -> str | None` — `None`이면 준비됨, 아니면 `"no_workspace"`/`"no_config"`
  - `stage_upload(workspace: Path, files: list[tuple[str, bytes]]) -> dict` → `{"upload_id": str, "items": [{"name","title","chars","preview","status","reason","duplicate_of"}]}`
  - `discard_upload(workspace: Path, upload_id: str) -> None`
  - `commit_upload(workspace: Path, upload_id: str, choices: list[dict], today: date | None = None) -> dict` → `{"batch_id","source_ids","primary","reference"}`; `choices` 항목 `{"name","title","type":"primary"|"reference","include":bool}`

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_manuscripts.py`

```python
from datetime import date

import pytest

from core import manuscripts as ms

LONG = "은혜의 말씀을 나눕니다. " * 30  # 공백 제외 200자 이상


def _ws(tmp_path, author_line='  name: "김목사"'):
    ws = tmp_path / "ws"
    (ws / "raw" / "entries").mkdir(parents=True)
    (ws / "config.yaml").write_text(
        f"workspace: {ws}\nauthor:\n  id: \"kim\"\n{author_line}\n", encoding="utf-8")
    return ws


def _front(path):
    head = path.read_text(encoding="utf-8").split("---\n")[1]
    out = {}
    for line in head.splitlines():
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip().strip('"')
    return out


def test_hash_normalization_matches_collect_rules():
    a = "  제목\r\n\r\n\r\n\r\n본문\t끝  "
    b = "제목\n\n본문    끝"
    assert ms.normalize_body(a) == b
    assert ms.content_hash(a) == ms.content_hash(b)
    assert ms.content_hash(a).startswith("sha256:") and len(ms.content_hash(a)) == 71


def test_workspace_ready(tmp_path):
    assert ms.workspace_ready(None) == "no_workspace"
    bare = tmp_path / "bare"
    bare.mkdir()
    assert ms.workspace_ready(bare) == "no_config"
    assert ms.workspace_ready(_ws(tmp_path)) is None


def test_stage_statuses_ok_empty_duplicate_error(tmp_path):
    ws = _ws(tmp_path)
    res = ms.stage_upload(ws, [
        ("1월 설교.md", ("# 주일 설교\n\n" + LONG).encode()),
        ("짧은.md", "짧다".encode()),
        ("같은 원고.md", ("# 주일 설교\n\n" + LONG).encode()),
        ("표.xlsx", b"x"),
    ])
    st = {i["name"]: i for i in res["items"]}
    assert st["1월 설교.md"]["status"] == "ok"
    assert st["1월 설교.md"]["title"] == "주일 설교"
    assert st["짧은.md"]["status"] == "empty"
    assert st["같은 원고.md"]["status"] == "duplicate"
    assert st["표.xlsx"]["status"] == "error"
    assert not list((ws / "raw" / "entries").iterdir())  # 확인 전에는 기록하지 않음


def test_commit_writes_schema_entries_and_moves_sources(tmp_path):
    ws = _ws(tmp_path)
    up = ms.stage_upload(ws, [("../../밖으로.md", ("# 주일 설교\n\n" + LONG).encode()),
                             ("주석.txt", ("로마서 주석\n\n" + LONG).encode())])
    names = [i["name"] for i in up["items"]]
    res = ms.commit_upload(ws, up["upload_id"], [
        {"name": names[0], "title": "정죄함이 없는 자유", "type": "primary", "include": True},
        {"name": names[1], "title": "로마서 주석", "type": "reference", "include": True},
    ], today=date(2026, 9, 30))
    assert res["batch_id"] == "batch_20260930"
    assert res["source_ids"] == ["src_20260930_001", "src_20260930_002"]
    assert (res["primary"], res["reference"]) == (1, 1)
    e1 = ws / "raw" / "entries" / "20260930_src_20260930_001.md"
    f = _front(e1)
    for key in ["source_id", "batch_id", "type", "category", "title", "author", "source_url",
                "source_path", "ingested_at", "confidence", "content_hash", "tags",
                "absorbed", "deleted", "parent_source_id", "part", "total_parts", "part_title"]:
        assert key in f, key
    assert f["type"] == "primary" and f["author"] == "김목사" and f["category"] == "sermon"
    assert f["absorbed"] == "false" and f["title"] == "정죄함이 없는 자유"
    f2 = _front(ws / "raw" / "entries" / "20260930_src_20260930_002.md")
    assert f2["type"] == "reference" and f2["author"] == "" and f2["category"] == "article"
    assert f["source_path"].startswith("raw/sources/20260930/")
    assert (ws / f["source_path"]).is_file()
    assert not (tmp_path / "밖으로.md").exists()  # 작업 폴더 밖에 쓰지 않음
    assert not (ws / "raw" / "sources" / "_staging" / up["upload_id"]).exists()


def test_commit_excluded_and_nonok_items_skipped(tmp_path):
    ws = _ws(tmp_path)
    up = ms.stage_upload(ws, [("a.md", ("# A\n\n" + LONG).encode()),
                              ("b.md", "짧다".encode())])
    res = ms.commit_upload(ws, up["upload_id"], [
        {"name": "a.md", "title": "A", "type": "primary", "include": False},
        {"name": "b.md", "title": "B", "type": "primary", "include": True},
    ], today=date(2026, 9, 30))
    assert res["source_ids"] == []


def test_numbering_continues_same_day_and_duplicates_existing(tmp_path):
    ws = _ws(tmp_path)
    for n in range(2):
        up = ms.stage_upload(ws, [(f"s{n}.md", (f"# 설교 {n}\n\n" + LONG + str(n)).encode())])
        ms.commit_upload(ws, up["upload_id"], [
            {"name": f"s{n}.md", "title": f"설교 {n}", "type": "primary", "include": True}],
            today=date(2026, 9, 30))
    assert sorted(p.name for p in (ws / "raw" / "entries").iterdir()) == [
        "20260930_src_20260930_001.md", "20260930_src_20260930_002.md"]
    again = ms.stage_upload(ws, [("s0 복사.md", ("# 설교 0\n\n" + LONG + "0").encode())])
    item = again["items"][0]
    assert item["status"] == "duplicate" and item["duplicate_of"] == "src_20260930_001"


def test_long_manuscript_split_into_parts(tmp_path):
    ws = _ws(tmp_path)
    body = "\n\n".join(f"## {i}장\n" + "\n".join(f"{i}-{j} 문장입니다." for j in range(300))
                       for i in range(1, 4))  # 약 900줄
    up = ms.stage_upload(ws, [("책.md", body.encode())])
    res = ms.commit_upload(ws, up["upload_id"], [
        {"name": "책.md", "title": "책", "type": "primary", "include": True}],
        today=date(2026, 9, 30))
    assert len(res["source_ids"]) >= 2
    parts = sorted((ws / "raw" / "entries").iterdir())
    fronts = [_front(p) for p in parts]
    assert all(f["parent_source_id"] == fronts[0]["parent_source_id"] != "" for f in fronts)
    assert [int(f["part"]) for f in fronts] == list(range(1, len(fronts) + 1))
    assert all(int(f["total_parts"]) == len(fronts) for f in fronts)
    assert all(p.read_text(encoding="utf-8").count("\n") <= 520 for p in parts)


def test_author_missing_in_config_is_blank(tmp_path):
    ws = _ws(tmp_path, author_line="  role: 담임목사")
    up = ms.stage_upload(ws, [("a.md", ("# A\n\n" + LONG).encode())])
    ms.commit_upload(ws, up["upload_id"], [
        {"name": "a.md", "title": "A", "type": "primary", "include": True}],
        today=date(2026, 9, 30))
    assert _front(next((ws / "raw" / "entries").iterdir()))["author"] == ""


def test_discard_upload(tmp_path):
    ws = _ws(tmp_path)
    up = ms.stage_upload(ws, [("a.md", ("# A\n\n" + LONG).encode())])
    ms.discard_upload(ws, up["upload_id"])
    assert not (ws / "raw" / "sources" / "_staging" / up["upload_id"]).exists()
    with pytest.raises(ValueError):
        ms.discard_upload(ws, "../../etc")
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest -q tests/test_manuscripts.py`
Expected: FAIL — `ImportError: cannot import name 'manuscripts'`

- [ ] **Step 3: 구현** — `core/manuscripts.py`

```python
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
```

> 참고: `_next_number` 의 walrus(`:=`)는 3.8+라 3.9 호환.

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest -q tests/test_manuscripts.py`
Expected: PASS (9 tests). 분할 테스트가 파트 줄 수 조건으로 실패하면 `_split` 의 `SPLIT_LINES` 경계(`>=`)를 확인한다.

- [ ] **Step 5: Commit**

```bash
git add core/manuscripts.py tests/test_manuscripts.py
git commit -m "원고 스테이징·raw entry 기록 — publish-collect 규칙(해시·번호·분할·스키마) 준수"
```

---

### Task 3: 규칙 후보 — store 이관과 증류 확장

**Files:**
- Modify: `core/store.py` (`_SCHEMA` 뒤 이관, `add_rule`, `list_rules`, `set_rule_active`, 지시 문장 메서드)
- Modify: `core/distill.py`
- Test: `tests/test_rule_candidates.py`

**Interfaces:**
- Produces (store): `add_rule(rule, source_ids, pending=False) -> int`; `list_rules()` 각 항목에 `"pending": bool`; `set_rule_active(id, True)`는 `pending=0`도 설정; `directive_messages(limit=20) -> list[{"id": int, "text": str}]`; `count_undistilled_directives() -> int`; `mark_directives_distilled(up_to_message_id: int) -> None`
- Produces (distill): 반환 dict에 `"candidates": [rule, ...]` 추가

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_rule_candidates.py`

```python
import json
import sqlite3

from core.distill import distill
from core.store import Store


def _user(store, text):
    sid = store.create_session("s")
    return store.add_message(sid, "user", [{"type": "text", "text": text}])


def _fake_chat(payload):
    def chat(prompt, session_ref=None, cfg=None):
        chat.prompt = prompt
        yield {"type": "done", "text": json.dumps(payload, ensure_ascii=False)}
    return chat


def test_legacy_db_gets_pending_and_last_message_columns(tmp_path):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE learned_rules(id INTEGER PRIMARY KEY AUTOINCREMENT, rule TEXT NOT NULL,"
        " source TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1,"
        " created_at TEXT NOT NULL DEFAULT (datetime('now')));"
        "CREATE TABLE distill_state(id INTEGER PRIMARY KEY CHECK(id=1),"
        " last_feedback_id INTEGER NOT NULL DEFAULT 0);"
        "INSERT INTO learned_rules(rule) VALUES ('기존 규칙');")
    con.commit()
    con.close()
    store = Store(db)
    rules = store.list_rules(active_only=False)
    assert rules[0]["rule"] == "기존 규칙" and rules[0]["pending"] is False
    assert store.count_undistilled_directives() == 0


def test_directive_messages_only_persistent_preferences(tmp_path):
    store = Store(tmp_path / "t.db")
    a = _user(store, "앞으로 서론은 항상 짧게 써 주세요")
    _user(store, "로마서 8장 초안 잡아줘")
    b = _user(store, "예화는 두 개 이상 넣지 말아 주세요")
    got = store.directive_messages()
    assert [m["id"] for m in got] == [a, b]
    assert store.count_undistilled_directives() == 2
    store.mark_directives_distilled(a)
    assert [m["id"] for m in store.directive_messages()] == [b]


def test_distill_saves_conversation_rules_as_pending(tmp_path):
    store = Store(tmp_path / "t.db")
    mid = _user(store, "앞으로 서론은 항상 짧게 써 주세요")
    chat = _fake_chat([{"rule": "서론은 짧게 쓴다", "source_ids": [f"m{mid}"],
                        "from": "conversation"}])
    res = distill(store, chat)
    assert res["candidates"] == ["서론은 짧게 쓴다"] and res["added"] == []
    assert "대화 지시" in chat.prompt and "서론은 항상 짧게" in chat.prompt
    rule = store.list_rules(active_only=False)[0]
    assert rule["pending"] is True and rule["active"] is False
    assert store.list_rules(active_only=True) == []
    store.set_rule_active(rule["id"], True)
    rule = store.list_rules(active_only=False)[0]
    assert rule["pending"] is False and rule["active"] is True
    assert store.count_undistilled_directives() == 0


def test_distill_feedback_rules_stay_active(tmp_path):
    store = Store(tmp_path / "t.db")
    sid = store.create_session("s")
    mid = store.add_message(sid, "assistant", [{"type": "text", "text": "답"}])
    fid = store.add_feedback(mid, "down", "너무 길다")
    res = distill(store, _fake_chat([{"rule": "짧게 답한다", "source_ids": [fid]}]))
    assert res["added"] == ["짧게 답한다"]
    assert store.list_rules(active_only=True)[0]["pending"] is False


def test_distill_nothing_new(tmp_path):
    store = Store(tmp_path / "t.db")
    assert distill(store, _fake_chat([]))["skipped"]
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest -q tests/test_rule_candidates.py`
Expected: FAIL — `KeyError: 'pending'` / `AttributeError: 'Store' object has no attribute 'directive_messages'`

- [ ] **Step 3: store 구현** — `core/store.py`

`Store.__init__` 의 `c.executescript(_SCHEMA)` 다음 줄에 `self._migrate(c)` 추가, 메서드 추가:

```python
DIRECTIVE_RE = re.compile(r"(앞으로|항상|늘 |매번|계속|기억해|원칙|하지 ?마|말아|지 ?말고)")

    def _migrate(self, c) -> None:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(learned_rules)")}
        if "pending" not in cols:
            c.execute("ALTER TABLE learned_rules ADD COLUMN pending INTEGER NOT NULL DEFAULT 0")
        cols = {r["name"] for r in c.execute("PRAGMA table_info(distill_state)")}
        if "last_message_id" not in cols:
            c.execute("ALTER TABLE distill_state ADD COLUMN last_message_id INTEGER NOT NULL DEFAULT 0")
```

(`core/store.py` 상단에 `import re` 추가. `DIRECTIVE_RE` 는 모듈 상단 상수.)

기존 메서드 교체:

```python
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
```

추가 메서드:

```python
    def _last_message_id(self) -> int:
        row = self._conn().execute(
            "SELECT last_message_id FROM distill_state WHERE id=1").fetchone()
        return row["last_message_id"] if row else 0

    def directive_messages(self, limit: int = 20) -> list[dict]:
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
```

- [ ] **Step 4: distill 구현** — `core/distill.py`

`_PROMPT_TMPL` 끝(피드백 목록 뒤)에 구획 추가하고 출력 형식에 `from` 설명을 넣는다:

```python
_PROMPT_TMPL = """\
다음은 사용자가 이전 답변에 남긴 교정/비선호 피드백과, 대화 중 사용자가 직접 밝힌 지시다.
여기서 사용자의 명시적이고 지속적인 선호를 규칙 문장으로 추출하라.
기존 규칙과 중복되지 않는 것만 뽑는다. 각 규칙은 한 문장, 최대 5개.
이번 원고나 이번 대화에만 해당하는 일회성 요청은 규칙으로 만들지 않는다.
반드시 JSON 배열만 출력하라. 다른 설명 텍스트를 붙이지 마라.
형식: [{{"rule": "...", "source_ids": [...], "from": "feedback" 또는 "conversation"}}]
대화 지시에서 나온 규칙은 from을 "conversation"으로, source_ids에 "m{{id}}"를 넣는다.

기존 활성 규칙:
{existing_rules}

피드백 목록:
{feedback_items}

대화 지시:
{directive_items}
"""
```

`_build_prompt(items, existing_rules, directives)` 로 바꾸고 `directive_items="\n".join(f"- [id=m{d['id']}] {d['text']!r}" for d in directives) or "(없음)"`, `feedback_items` 가 비면 `"(없음)"`.

`distill()` 본문:

```python
def distill(store, chat_fn, cfg=None) -> dict:
    items = _collect_context(store)
    directives = store.directive_messages()
    if not items and not directives:
        return {"added": [], "candidates": [], "skipped": "no new feedback"}
    prompt = _build_prompt(items, store.list_rules(active_only=True), directives)
    # (provider 호출·파싱 루프는 기존과 동일, 단 entry 검증 뒤)
    #   origin = entry.get("from", "feedback")
    #   parsed_rules.append((rule, source_ids, origin == "conversation"))
    for rule, source_ids, pending in parsed_rules:
        store.add_rule(rule, source_ids, pending=pending)
    if items:
        store.mark_distilled(max(it["id"] for it in items))
    if directives:
        store.mark_directives_distilled(max(d["id"] for d in directives))
    return {"added": [r for r, _, p in parsed_rules if not p],
            "candidates": [r for r, _, p in parsed_rules if p]}
```

파싱 실패 시 기존처럼 저장 0건·`{"added": [], "candidates": [], "error": "parse"}` 반환. `source_ids` 검증은 `isinstance(source_ids, list)` 유지(문자열 `m12` 허용).

- [ ] **Step 5: 통과 확인(신규 + 기존 증류 회귀)**

Run: `.venv/bin/python -m pytest -q tests/test_rule_candidates.py tests/test_distill.py tests/test_store.py`
Expected: PASS. 기존 `test_distill.py` 가 반환 dict 전체를 비교하면 `"candidates": []` 를 기대값에 추가한다.

- [ ] **Step 6: Commit**

```bash
git add core/store.py core/distill.py tests/test_rule_candidates.py tests/test_distill.py
git commit -m "대화 지시를 규칙 후보로 — pending 규칙, DB 이관, 증류 입력 확장"
```

---

### Task 4: 학습 작업 관리자

**Files:**
- Create: `core/learning.py`
- Test: `tests/test_learning_jobs.py`

**Interfaces:**
- Consumes: provider `chat(prompt, session_ref=None, cfg=dict) -> Iterator[dict]` (이벤트 `delta`/`done`/`error`)
- Produces: `LearningManager(data_dir: Path, chat_fn=None, run_async=True)`; `.create(workspace: str, commit: dict, cfg: dict) -> dict`; `.get(job_id) -> dict | None`; `.list() -> list[dict]`; `.retry(job_id, cfg) -> dict`. 상태 필드: `id, status(queued|absorbing|profiling|completed|failed), stage, batch_id, source_ids, primary, reference, workspace, log(list[str]), error, pid, created_at, updated_at`.

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_learning_jobs.py`

```python
import json

from core.learning import LearningManager


def _chat(fail_on=None):
    calls = []

    def chat(prompt, session_ref=None, cfg=None):
        calls.append({"prompt": prompt, "cfg": dict(cfg or {})})
        if fail_on and fail_on in prompt:
            yield {"type": "error", "error": "boom"}
            return
        yield {"type": "delta", "text": "진행 중"}
        yield {"type": "done", "text": "완료"}
    chat.calls = calls
    return chat


COMMIT = {"batch_id": "batch_20260930", "source_ids": ["src_20260930_001"],
          "primary": 1, "reference": 0}


def test_absorb_then_profile_with_accept_edits_only_for_job(tmp_path):
    chat = _chat()
    m = LearningManager(tmp_path, chat_fn=chat, run_async=False)
    cfg = {"claude_permission_mode": "default", "workspace_dir": "/ws"}
    job = m.create("/ws", COMMIT, cfg)
    job = m.get(job["id"])
    assert job["status"] == "completed"
    assert [c["prompt"].split()[0] for c in chat.calls] == ["/publish-absorb", "/publish-profile"]
    assert "src_20260930_001" in chat.calls[0]["prompt"]
    assert all(c["cfg"]["claude_permission_mode"] == "acceptEdits" for c in chat.calls)
    assert all(c["cfg"]["workspace_dir"] == "/ws" for c in chat.calls)
    assert cfg["claude_permission_mode"] == "default"  # 전역 설정 불변


def test_reference_only_batch_skips_profile(tmp_path):
    chat = _chat()
    m = LearningManager(tmp_path, chat_fn=chat, run_async=False)
    job = m.create("/ws", {**COMMIT, "primary": 0, "reference": 1}, {})
    assert m.get(job["id"])["status"] == "completed"
    assert len(chat.calls) == 1


def test_provider_error_marks_failed_and_retry_runs_again(tmp_path):
    m = LearningManager(tmp_path, chat_fn=_chat(fail_on="/publish-absorb"), run_async=False)
    job = m.create("/ws", COMMIT, {})
    failed = m.get(job["id"])
    assert failed["status"] == "failed" and "boom" in failed["error"]
    m.chat_fn = _chat()
    assert m.retry(job["id"], {})["status"] == "completed"


def test_interrupted_job_from_previous_process_becomes_failed(tmp_path):
    m = LearningManager(tmp_path, chat_fn=_chat(), run_async=False)
    job = m.create("/ws", COMMIT, {})
    path = tmp_path / "learning" / job["id"] / "status.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(status="absorbing", pid=-1)
    path.write_text(json.dumps(data), encoding="utf-8")
    got = m.get(job["id"])
    assert got["status"] == "failed" and "중단" in got["error"]
    assert [j["id"] for j in m.list()] == [job["id"]]
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest -q tests/test_learning_jobs.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.learning'`

- [ ] **Step 3: 구현** — `core/learning.py`

```python
"""원고 학습 작업 — 기록된 배치를 Claude로 흡수(publish-absorb)하고
목사님 원고가 있으면 문체 프로필(publish-profile)을 갱신한다."""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

_LOCK = threading.Lock()
_RUNNING = {"absorbing", "profiling", "queued"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def absorb_prompt(batch_id: str, source_ids: list[str]) -> str:
    return (f"/publish-absorb 이번 배치 {batch_id} 의 미흡수 항목({', '.join(source_ids)})을 "
            "위키에 흡수하세요. type: reference 항목은 참고자료로만 분류하고 "
            "저자(목사님)의 입장으로 쓰지 마세요. 확인 질문 없이 끝까지 진행하고, "
            "마지막에 흡수 결과를 한 문단으로 요약하세요.")


def profile_prompt(batch_id: str) -> str:
    return (f"/publish-profile 방금 흡수한 {batch_id} 의 목사님 원고(type: primary)를 반영해 "
            "문체 프로필과 설교 팩을 증분 갱신하세요. 참고자료(type: reference)는 분석에서 "
            "제외합니다. 확인 질문 없이 끝까지 진행하고 바뀐 점을 요약하세요.")


class LearningManager:
    def __init__(self, data_dir: Path, chat_fn=None, run_async: bool = True):
        self.root = Path(data_dir) / "learning"
        self.root.mkdir(parents=True, exist_ok=True)
        if chat_fn is None:
            from core import providers
            chat_fn = providers.get("claude").chat
        self.chat_fn = chat_fn
        self.run_async = run_async

    def _path(self, job_id: str) -> Path:
        return self.root / job_id / "status.json"

    def _write(self, job_id: str, **patch) -> dict:
        with _LOCK:
            path = self._path(job_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            cur = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
            cur.update(patch, updated_at=_now())
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
            return cur

    def get(self, job_id: str) -> dict | None:
        if not re.fullmatch(r"[0-9a-f]{12}", job_id or ""):
            return None
        path = self._path(job_id)
        if not path.is_file():
            return None
        job = json.loads(path.read_text(encoding="utf-8"))
        if job.get("status") in _RUNNING and job.get("pid") != os.getpid():
            job = self._write(job_id, status="failed", stage="중단됨",
                              error="앱이 종료되어 학습이 중단되었습니다. 다시 시도해 주세요.")
        return job

    def list(self) -> list[dict]:
        jobs = [self.get(p.parent.name) for p in self.root.glob("*/status.json")]
        return sorted([j for j in jobs if j], key=lambda j: j.get("created_at", ""), reverse=True)

    def create(self, workspace: str, commit: dict, cfg: dict) -> dict:
        job_id = uuid.uuid4().hex[:12]
        self._write(job_id, id=job_id, status="queued", stage="학습 대기 중",
                    batch_id=commit["batch_id"], source_ids=list(commit["source_ids"]),
                    primary=int(commit.get("primary", 0)),
                    reference=int(commit.get("reference", 0)),
                    workspace=workspace, log=[], error=None, pid=os.getpid(),
                    created_at=_now())
        self._dispatch(job_id, cfg)
        return self.get(job_id)

    def retry(self, job_id: str, cfg: dict) -> dict:
        job = self.get(job_id)
        if not job:
            raise ValueError("작업을 찾을 수 없습니다")
        if job["status"] != "failed":
            raise ValueError("실패한 작업만 다시 시도할 수 있습니다")
        self._write(job_id, status="queued", stage="다시 시도 대기 중", error=None,
                    pid=os.getpid())
        self._dispatch(job_id, cfg)
        return self.get(job_id)

    def _dispatch(self, job_id: str, cfg: dict):
        if self.run_async:
            threading.Thread(target=self._run, args=(job_id, dict(cfg)), daemon=True).start()
        else:
            self._run(job_id, dict(cfg))

    def _log(self, job_id: str, text: str):
        job = self.get(job_id) or {}
        self._write(job_id, log=(list(job.get("log") or []) + [text[-2000:]])[-80:])

    def _step(self, job_id: str, prompt: str, cfg: dict) -> str | None:
        """한 단계 실행. 오류 메시지를 돌려주고, 성공이면 None."""
        final = None
        for ev in self.chat_fn(prompt, session_ref=None, cfg=cfg):
            if ev.get("type") == "error":
                return str(ev.get("error") or "알 수 없는 오류")
            if ev.get("type") == "done":
                final = ev.get("text") or ""
        if final is None:
            return "Claude 응답이 끝나지 않았습니다"
        self._log(job_id, final)
        return None

    def _run(self, job_id: str, cfg: dict):
        job = self.get(job_id)
        run_cfg = dict(cfg)
        run_cfg["claude_permission_mode"] = "acceptEdits"
        run_cfg["workspace_dir"] = job["workspace"]
        self._write(job_id, status="absorbing", stage="위키에 흡수하는 중", pid=os.getpid())
        err = self._step(job_id, absorb_prompt(job["batch_id"], job["source_ids"]), run_cfg)
        if err is None and job.get("primary"):
            self._write(job_id, status="profiling", stage="문체 프로필 갱신 중")
            err = self._step(job_id, profile_prompt(job["batch_id"]), run_cfg)
        if err:
            self._write(job_id, status="failed", stage="실패", error=err)
        else:
            self._write(job_id, status="completed", stage="학습 완료")
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest -q tests/test_learning_jobs.py`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add core/learning.py tests/test_learning_jobs.py
git commit -m "원고 학습 작업 관리자 — 흡수→프로필, 이 작업만 acceptEdits, 중단 복구"
```

---

### Task 5: 서버 경로

**Files:**
- Modify: `core/server.py` (import, `api_path` 목록, `do_GET`/`do_POST`/`do_DELETE`, `_multipart_files`, 증류 문턱)
- Test: `tests/test_server.py` (끝에 추가)

**Interfaces:**
- Consumes: `manuscripts.workspace_ready/stage_upload/commit_upload/discard_upload`, `LearningManager`
- Produces (HTTP, 모두 Bearer):
  - `GET /learning/status` → `{"ready": bool, "reason": str|null, "workspace_dir": str|null, "jobs": [...]}`
  - `POST /learning/uploads` (multipart, 필드명 `files` 반복) → `stage_upload` 결과
  - `POST /learning/jobs` `{upload_id, items}` → 202 작업(`source_ids` 비면 400)
  - `POST /learning/jobs/{id}/retry` → 202
  - `DELETE /learning/uploads/{id}` → `{"ok": true}`
  - `GET /rules` 에 `"undistilled_directives"` 추가

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_server.py` 끝에 추가

```python
def _multi(url, path, files, token=TOKEN):
    boundary = "----kairos-learn"
    chunks = []
    for name, data in files:
        chunks.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; "
            f"filename=\"{name}\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode()
            + data + b"\r\n")
    body = b"".join(chunks) + f"--{boundary}--\r\n".encode()
    r = urllib.request.Request(url + path, data=body, method="POST")
    r.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    if token:
        r.add_header("Authorization", f"Bearer {token}")
    return urllib.request.urlopen(r)


def test_learning_flow_upload_commit_job(srv, tmp_path, monkeypatch):
    url, _ = srv
    from core import settings
    monkeypatch.setenv("KAIROS_CONFIG_DIR", str(tmp_path / "cfg"))
    ws = tmp_path / "ws"
    (ws / "raw" / "entries").mkdir(parents=True)
    (ws / "config.yaml").write_text("author:\n  name: \"김목사\"\n", encoding="utf-8")
    settings.save({"workspace_dir": str(ws)})

    def fake_chat(prompt, session_ref=None, cfg=None):
        yield {"type": "done", "text": "ok"}
    monkeypatch.setattr("core.server._learning_chat", lambda: fake_chat)

    st = json.load(_req(url, "/learning/status"))
    assert st["ready"] is True and st["jobs"] == []
    up = json.load(_multi(url, "/learning/uploads",
                          [("설교.md", ("# 주일 설교\n\n" + "은혜의 말씀 " * 60).encode())]))
    item = up["items"][0]
    assert item["status"] == "ok"
    job = json.load(_req(url, "/learning/jobs", {
        "upload_id": up["upload_id"],
        "items": [{"name": item["name"], "title": "설교", "type": "primary", "include": True}]}))
    assert job["source_ids"] and job["batch_id"].startswith("batch_")
    assert list((ws / "raw" / "entries").glob("*.md"))


def test_learning_requires_token_and_reports_missing_config(srv, tmp_path, monkeypatch):
    url, _ = srv
    from core import settings
    monkeypatch.setenv("KAIROS_CONFIG_DIR", str(tmp_path / "cfg"))
    with pytest.raises(urllib.error.HTTPError) as e:
        _req(url, "/learning/status", token=None)
    assert e.value.code == 401
    bare = tmp_path / "bare"
    bare.mkdir()
    settings.save({"workspace_dir": str(bare)})
    st = json.load(_req(url, "/learning/status"))
    assert st["ready"] is False and st["reason"] == "no_config"
    with pytest.raises(urllib.error.HTTPError) as e:
        _multi(url, "/learning/uploads", [("a.md", b"x")])
    assert e.value.code == 400
```

> 작업 실행이 실제 claude를 부르지 않도록 서버는 `_learning_chat()` 모듈 함수(기본 `providers.get("claude").chat` 반환)를 요청 때마다 호출해 chat 함수를 얻고, 테스트는 이 함수를 monkeypatch 한다.

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest -q tests/test_server.py -k learning`
Expected: FAIL (404 / JSONDecodeError)

- [ ] **Step 3: 구현** — `core/server.py`

import 추가:

```python
from core import manuscripts
from core.learning import LearningManager


def _learning_chat():
    return providers.get("claude").chat
```

`api_path` 튜플에 `"/learning/status"` 추가. `do_GET` 의 인증 블록 안(`/rules` 근처)에:

```python
                if u.path == "/learning/status":
                    return self._learning_status()
```

`/rules` 응답에 `"undistilled_directives": store.count_undistilled_directives()` 추가.

Handler 메서드:

```python
        def _learning_manager(self) -> LearningManager:
            return LearningManager(self._data_dir(), chat_fn=_learning_chat())

        def _learning_workspace(self):
            ws = settings.load().get("workspace_dir")
            path = Path(ws).expanduser() if ws else None
            return path, manuscripts.workspace_ready(path)

        def _learning_status(self):
            ws, reason = self._learning_workspace()
            return self._send(200, {"ready": reason is None, "reason": reason,
                                     "workspace_dir": str(ws) if ws else None,
                                     "jobs": self._learning_manager().list()})

        def _multipart_files(self) -> list[tuple[str, bytes]] | None:
            ctype = self.headers.get("Content-Type", "")
            if not ctype.lower().startswith("multipart/form-data"):
                return None
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return None
            if length <= 0 or length > 200 * 1024 * 1024:
                return None
            raw = self.rfile.read(length)
            message = BytesParser(policy=policy.default).parsebytes(
                f"Content-Type: {ctype}\r\nMIME-Version: 1.0\r\n\r\n".encode() + raw)
            files = []
            for part in message.iter_parts():
                if part.get_param("name", header="content-disposition") == "files" \
                        and part.get_filename():
                    files.append((part.get_filename(), part.get_payload(decode=True) or b""))
            return files or None
```

`do_POST` 에서 `/presentations` 처리 **앞**에 (body를 읽기 전):

```python
            if self.path == "/learning/uploads":
                ws, reason = self._learning_workspace()
                if reason:
                    return self._send(400, {"error": reason})
                files = self._multipart_files()
                if files is None:
                    return self._send(400, {"error": "bad multipart upload"})
                return self._send(200, manuscripts.stage_upload(ws, files))
            m = re.fullmatch(r"/learning/jobs/([0-9a-f]{12})/retry", self.path)
            if m:
                try:
                    job = self._learning_manager().retry(m.group(1), settings.load())
                except ValueError as exc:
                    return self._send(400, {"error": str(exc)})
                return self._send(202, job)
```

`body = self._body()` 이후 분기에:

```python
            if self.path == "/learning/jobs":
                ws, reason = self._learning_workspace()
                if reason:
                    return self._send(400, {"error": reason})
                try:
                    commit = manuscripts.commit_upload(
                        ws, str(body.get("upload_id", "")), list(body.get("items") or []))
                except (OSError, ValueError, KeyError) as exc:
                    return self._send(400, {"error": str(exc)})
                if not commit["source_ids"]:
                    return self._send(400, {"error": "학습할 원고가 없습니다"})
                job = self._learning_manager().create(str(ws), commit, settings.load())
                return self._send(202, job)
```

`do_DELETE` 에(인증 확인 뒤):

```python
            m = re.fullmatch(r"/learning/uploads/([0-9a-f]{12})", self.path)
            if m:
                ws, reason = self._learning_workspace()
                if reason:
                    return self._send(400, {"error": reason})
                manuscripts.discard_upload(ws, m.group(1))
                return self._send(200, {"ok": True})
```

자동 증류 문턱(`store.count_undistilled_feedback() >= DISTILL_THRESHOLD`)을
`store.count_undistilled_feedback() + store.count_undistilled_directives() >= DISTILL_THRESHOLD` 로 바꾼다.

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest -q tests/test_server.py`
Expected: PASS (기존 + 신규 2)

- [ ] **Step 5: Commit**

```bash
git add core/server.py tests/test_server.py
git commit -m "원고 학습 API — 다중 파일 업로드·기록·작업·재시도·취소, 증류 문턱에 대화 지시 포함"
```

---

### Task 6: 참고자료 인용 원칙 (publish_agent)

**Files (별도 저장소 `~/LocalProjects/publish_agent`, main):**
- Modify: `skills/publish-write/SKILL.md` — `## 설교 팩 (Sermon Pack)` 바로 앞
- Modify: `skills/publish-sermon/SKILL.md` — `## 설교 팩 (Sermon Pack)` 바로 앞

- [ ] **Step 1: 두 파일의 `## 설교 팩 (Sermon Pack)` 제목 바로 앞에 같은 섹션 삽입**

```markdown
## 참고자료 사용 원칙

위키의 `references/` 기사와 `type: reference` 원문은 목사님의 글이 아니다.

- 참고자료는 **출처를 밝힌 인용이나 요약**으로만 쓴다. 예: "○○의 『△△』에 따르면 …"
- 참고자료의 주장·해석을 목사님의 신학적 입장이나 고백, 문장으로 바꿔 쓰지 않는다.
  목사님의 입장은 `type: primary` 원고와 그로부터 만든 위키 기사에서만 가져온다.
- 문체(어미·호칭·리듬·설교 구조)는 오직 설교 팩(primary 원고 기반)을 따른다.
  참고자료의 문체를 흉내 내지 않는다.
- 참고자료와 목사님 입장이 다르면 둘을 섞지 말고, 목사님 입장을 본문으로 두고
  참고자료는 비교 자료로 밝혀 둔다.

```

- [ ] **Step 2: 검증**

Run: `cd ~/LocalProjects/publish_agent && grep -c "## 참고자료 사용 원칙" skills/publish-write/SKILL.md skills/publish-sermon/SKILL.md && python3 -m pytest -q tests`
Expected: 각 파일 `1`, 테스트 PASS

- [ ] **Step 3: Commit (publish_agent main)**

```bash
cd ~/LocalProjects/publish_agent
git pull -q
git add skills/publish-write/SKILL.md skills/publish-sermon/SKILL.md
git commit -m "참고자료 사용 원칙 — 출처 밝힌 인용만, 목사님 입장·문체로 바꿔 쓰지 않음"
```

---

### Task 7: 화면 — 원고 학습 메뉴·규칙 후보 배지

**Files:**
- Create: `app/src/Learning.tsx`, `app/src/assets/icons/learn.png`
- Modify: `app/src/api.ts`, `app/src/Chat.tsx`, `app/src/Settings.tsx`, `app/src/index.css`

**Interfaces:**
- Consumes: Task 5 HTTP API
- Produces: `api.ts` — `learningStatus()`, `uploadManuscripts(files: File[])`, `startLearning(uploadId, items)`, `retryLearning(id)`, `discardUpload(id)`; 타입 `LearningItem`, `LearningJob`, `LearningStatus`; `Rule.pending: boolean`

- [ ] **Step 1: 메뉴 타일 생성 (Codex `$imagegen`)**

기존 도자기 메뉴 타일 프롬프트(스크래치 `emoji/m-*.txt`)와 같은 틀로 `learn` 프롬프트를 쓴다 — 장면: "absorbing manuscripts shown as a small stack of ivory ceramic manuscript sheets with walnut-brown lines, and a small walnut-brown ceramic open book beside it with a soft amber glow between them", 팔레트 `#F3EDE1 #8C5A2B #E0A24A #6E4520`, 투명 배경, `AR 1:1`.
`node ~/.claude/skills/image-prompt/scripts/check_prompt.mjs <파일>` → `ok:true` 확인 후 codex `$imagegen`(built-in, stdin `/dev/null`)으로 생성, 세션 id 폴더의 PNG를 가져와 알파 기준 정사각 크롭 후 128px로 `app/src/assets/icons/learn.png` 저장.

- [ ] **Step 2: api.ts 추가**

```ts
export type Rule = { id: number; rule: string; active: boolean; pending: boolean; created_at: string };

export type LearningItem = {
  name: string; title: string; chars: number; preview: string;
  status: "ok" | "empty" | "duplicate" | "error"; reason: string; duplicate_of: string;
};
export type LearningJob = {
  id: string; status: "queued" | "absorbing" | "profiling" | "completed" | "failed";
  stage: string; batch_id: string; source_ids: string[]; primary: number; reference: number;
  log: string[]; error: string | null; created_at: string; updated_at: string;
};
export type LearningStatus = {
  ready: boolean; reason: "no_workspace" | "no_config" | null;
  workspace_dir: string | null; jobs: LearningJob[];
};

export async function learningStatus(): Promise<LearningStatus> {
  const r = await fetch("/learning/status", { headers: HDRS });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
export async function uploadManuscripts(files: File[]): Promise<{ upload_id: string; items: LearningItem[] }> {
  const form = new FormData();
  files.forEach(f => form.append("files", f, f.name));
  const r = await fetch("/learning/uploads", {
    method: "POST", headers: { Authorization: HDRS.Authorization }, body: form });
  if (!r.ok) throw new Error((await r.json()).error ?? `HTTP ${r.status}`);
  return r.json();
}
export async function startLearning(
  uploadId: string,
  items: { name: string; title: string; type: "primary" | "reference"; include: boolean }[],
): Promise<LearningJob> {
  const r = await fetch("/learning/jobs", {
    method: "POST", headers: HDRS, body: JSON.stringify({ upload_id: uploadId, items }) });
  if (!r.ok) throw new Error((await r.json()).error ?? `HTTP ${r.status}`);
  return r.json();
}
export async function retryLearning(id: string): Promise<LearningJob> {
  const r = await fetch(`/learning/jobs/${id}/retry`, { method: "POST", headers: HDRS });
  if (!r.ok) throw new Error((await r.json()).error ?? `HTTP ${r.status}`);
  return r.json();
}
export async function discardUpload(id: string): Promise<void> {
  await fetch(`/learning/uploads/${id}`, { method: "DELETE", headers: HDRS });
}
```

(기존 `export type Rule = ...` 한 줄은 위 정의로 교체.)

- [ ] **Step 3: `app/src/Learning.tsx` 작성**

```tsx
import { useEffect, useRef, useState } from "react";
import { discardUpload, learningStatus, retryLearning, startLearning, uploadManuscripts } from "./api";
import type { LearningItem, LearningJob, LearningStatus } from "./api";
import { Emoji } from "./emoji";

type Row = LearningItem & { include: boolean; type: "primary" | "reference" };

const STATUS_LABEL: Record<LearningItem["status"], string> = {
  ok: "학습 가능", empty: "글자 거의 없음", duplicate: "이미 학습함", error: "변환 실패",
};
const JOB_LABEL: Record<LearningJob["status"], string> = {
  queued: "대기 중", absorbing: "흡수 중", profiling: "문체 갱신 중",
  completed: "완료", failed: "실패",
};
const ACCEPT = ".hwp,.hwpx,.docx,.pdf,.md,.markdown,.txt";

export default function Learning() {
  const [status, setStatus] = useState<LearningStatus | null>(null);
  const [uploadId, setUploadId] = useState<string | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  function refresh() {
    learningStatus().then(setStatus).catch(e => setError(String(e)));
  }
  useEffect(() => { refresh(); }, []);
  useEffect(() => {
    const running = status?.jobs.some(j => ["queued", "absorbing", "profiling"].includes(j.status));
    if (!running) return;
    const t = window.setInterval(refresh, 3000);
    return () => window.clearInterval(t);
  }, [status]);

  async function pick(files: FileList | null) {
    if (!files?.length) return;
    setBusy(true); setError("");
    try {
      if (uploadId) await discardUpload(uploadId);
      const res = await uploadManuscripts(Array.from(files));
      setUploadId(res.upload_id);
      setRows(res.items.map(i => ({ ...i, include: i.status === "ok", type: "primary" })));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); setDragging(false); }
  }

  function update(name: string, patch: Partial<Row>) {
    setRows(old => old.map(r => r.name === name ? { ...r, ...patch } : r));
  }

  async function start() {
    if (!uploadId) return;
    setBusy(true); setError("");
    try {
      await startLearning(uploadId, rows.map(r => ({
        name: r.name, title: r.title, type: r.type, include: r.include && r.status === "ok" })));
      setUploadId(null); setRows([]); refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }

  if (status && !status.ready) {
    return (
      <main className="page"><div className="page-inner narrow">
        <header className="page-header"><div>
          <span className="page-eyebrow">MANUSCRIPTS</span><h1>원고 학습</h1></div></header>
        <div className="notice warn">
          <Emoji name="warn" size={16} />{" "}
          {status.reason === "no_workspace"
            ? "설정에서 작업 폴더를 먼저 지정하세요."
            : "대화에서 /publish-setup 으로 워크스페이스를 먼저 초기화하세요."}
        </div>
      </div></main>
    );
  }

  const chosen = rows.filter(r => r.include && r.status === "ok");
  return (
    <main className="page"><div className="page-inner">
      <header className="page-header"><div>
        <span className="page-eyebrow">MANUSCRIPTS</span>
        <h1>원고 학습</h1>
        <p className="hint">목사님 원고와 참고자료를 올리면 위키에 흡수하고, 목사님 원고는 문체 프로필에도 반영합니다.</p>
      </div></header>

      <section className="card">
        <label className={`drop-zone ${dragging ? "is-dragging" : ""}`}
               onDragEnter={e => { e.preventDefault(); setDragging(true); }}
               onDragOver={e => { e.preventDefault(); setDragging(true); }}
               onDragLeave={e => { e.preventDefault(); if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false); }}
               onDrop={e => { e.preventDefault(); pick(e.dataTransfer.files); }}>
          <input ref={inputRef} type="file" multiple accept={ACCEPT}
                 onChange={e => pick(e.target.files)} />
          <span className="drop-icon"><Emoji name="upload" size={44} /></span>
          <strong>{busy ? "변환하는 중…" : "원고 파일을 끌어놓거나 선택하세요"}</strong>
          <small>HWP · HWPX · DOCX · PDF · MD · TXT / 여러 개 가능</small>
        </label>
        {error && <div className="notice error" style={{ marginTop: 12 }}>{error}</div>}
      </section>

      {rows.length > 0 && (
        <section className="card">
          <h3>올린 파일 확인 <span className="hint">{chosen.length}개 학습 예정</span></h3>
          <div className="learn-list">
            {rows.map(r => (
              <div key={r.name} className={`learn-row status-${r.status}`}>
                <input type="checkbox" checked={r.include} disabled={r.status !== "ok"}
                       onChange={e => update(r.name, { include: e.target.checked })}
                       aria-label={`${r.name} 포함`} />
                <div className="learn-main">
                  <input className="learn-title" value={r.title} disabled={r.status !== "ok"}
                         onChange={e => update(r.name, { title: e.target.value })} />
                  <small>{r.name} · {r.chars.toLocaleString()}자 · {STATUS_LABEL[r.status]}
                    {r.reason && ` — ${r.reason}`}
                    {r.duplicate_of && ` (${r.duplicate_of})`}</small>
                  {r.preview && <p className="learn-preview">{r.preview}</p>}
                </div>
                <select value={r.type} disabled={r.status !== "ok"}
                        onChange={e => update(r.name, { type: e.target.value as Row["type"] })}>
                  <option value="primary">목사님 원고</option>
                  <option value="reference">참고자료</option>
                </select>
              </div>
            ))}
          </div>
          <div className="field-row" style={{ marginTop: 14 }}>
            <button className="btn-primary" disabled={busy || !chosen.length} onClick={start}>
              학습 시작 ({chosen.length})
            </button>
            <button disabled={busy} onClick={async () => {
              if (uploadId) await discardUpload(uploadId);
              setUploadId(null); setRows([]);
            }}>취소</button>
          </div>
        </section>
      )}

      <section className="card">
        <h3>학습 기록</h3>
        {!status?.jobs.length && (
          <div className="empty-hint"><Emoji name="empty" size={40} /> 아직 학습한 원고가 없습니다.</div>
        )}
        <div className="stack">
          {status?.jobs.map(j => (
            <article key={j.id} className="job-item">
              <div className="job-row">
                <div>
                  <strong>{j.batch_id} · 원고 {j.primary}편 · 참고자료 {j.reference}편</strong>
                  <small>{new Date(j.created_at).toLocaleString("ko-KR")} · {j.stage}</small>
                </div>
                <span className={`job-status ${j.status === "completed" ? "completed" : j.status === "failed" ? "failed" : "running"}`}>
                  {JOB_LABEL[j.status]}
                </span>
              </div>
              {j.error && <div className="job-error">{j.error}</div>}
              {!!j.log.length && <details><summary>작업 로그</summary><pre>{j.log.join("\n\n")}</pre></details>}
              {j.status === "failed" && (
                <button className="retry-action" onClick={async () => {
                  try { await retryLearning(j.id); refresh(); }
                  catch (e) { setError(e instanceof Error ? e.message : String(e)); }
                }}>다시 시도</button>
              )}
            </article>
          ))}
        </div>
      </section>
    </div></main>
  );
}
```

- [ ] **Step 4: 메뉴 연결** — `app/src/Chat.tsx`

- import 추가: `import Learning from "./Learning";`, `import learnIcon from "./assets/icons/learn.png";`
- `useState<"chat" | "settings" | "bible" | "ppt">` → `useState<"chat" | "settings" | "bible" | "ppt" | "learn">`
- 메뉴 배열의 `ppt` 항목 뒤에:

```tsx
            { key: "learn", icon: learnIcon, label: "원고 학습",
              on: () => setView(v => v === "learn" ? "chat" : "learn"), active: view === "learn" },
```

- 본문 분기의 `) : view === "ppt" ? (<PresentationStudio />` 뒤에 `) : view === "learn" ? (<Learning />` 추가.

- [ ] **Step 5: 규칙 후보 배지** — `app/src/Settings.tsx` 의 `rules.map` 안 `{r.rule}` 를 다음으로:

```tsx
                {r.pending && <span className="rule-badge">후보</span>}{r.rule}
```

그리고 그 카드의 hint 줄(`미증류 피드백 {undistilled}건`) 뒤에 한 줄 안내 추가:

```tsx
        <div className="hint" style={{ marginTop: 6 }}>'후보'는 대화에서 뽑힌 규칙입니다. 켜야 답변에 반영됩니다.</div>
```

- [ ] **Step 6: 스타일** — `app/src/index.css` 끝에:

```css
/* ── 원고 학습 ───────────────────────────────────────────── */
.learn-list { display: grid; gap: 8px; }
.learn-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: start;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
}
.learn-row:not(.status-ok) { opacity: .6; }
.learn-row.status-error { border-color: var(--danger); }
.learn-main { display: grid; gap: 4px; min-width: 0; }
.learn-main small { color: var(--muted); font-size: 12px; }
.learn-title { width: 100%; font-weight: 600; }
.learn-preview { overflow: hidden; color: var(--ink-2); font-size: 13px; white-space: nowrap; text-overflow: ellipsis; }
.rule-badge {
  display: inline-block;
  margin-right: 6px;
  padding: 1px 7px;
  border-radius: 999px;
  color: var(--warn);
  background: var(--warn-soft);
  font-size: 11px;
  font-weight: 700;
}
@media (max-width: 800px) { .learn-row { grid-template-columns: auto 1fr; } .learn-row select { grid-column: 2; } }
```

- [ ] **Step 7: 빌드·린트**

Run: `cd app && npm run build && npx oxlint src`
Expected: `✓ built`, 린트 경고 0

- [ ] **Step 8: Commit**

```bash
git add app/src/Learning.tsx app/src/api.ts app/src/Chat.tsx app/src/Settings.tsx app/src/index.css app/src/assets/icons/learn.png
git commit -m "원고 학습 화면 — 다중 업로드·확인 목록·원고/참고자료 구분·학습 기록, 규칙 후보 배지"
```

---

### Task 8: 통합 확인과 머지

- [ ] **Step 1: 화면 캡처** — 임시 설정·데이터 폴더(`KAIROS_CONFIG_DIR`, `KAIROS_DATA_DIR`)와 `config.yaml`을 둔 임시 작업 폴더로 사이드카를 띄우고(Playwright), 다음을 밝은/다크 모드로 캡처해 확인한다: ① `config.yaml` 없는 안내 ② 파일 3개(정상·짧음·중복) 올린 확인 목록 ③ [학습 시작] 후 학습 기록 카드(`/learning/jobs` 는 실제 claude 대신 route 목으로 `completed` 응답) ④ 설정의 '후보' 배지(`/rules` 목).
- [ ] **Step 2: 머지 전 3종 체크**

Run: `.venv/bin/python -m pytest -q && (cd src-tauri && cargo test) && (cd app && npm run build)`
Expected: 전부 통과

- [ ] **Step 3: 머지·푸시**

```bash
git checkout main && git pull
git merge --no-ff feat/manuscript-learning -m "Merge feat/manuscript-learning: 원고 학습 메뉴"
git push origin main
cd ~/LocalProjects/publish_agent && git push origin main
```
