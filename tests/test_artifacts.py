"""core/artifacts.py 단위 테스트: 감지·보존."""
from __future__ import annotations

from pathlib import Path

from core.artifacts import collect, extract_artifacts


def test_extract_absolute_path(tmp_path):
    img = tmp_path / "shot.png"
    img.write_bytes(b"\x89PNG\r\n")
    text = f"결과 이미지는 {img} 에 저장했습니다."
    found = extract_artifacts(text, workspace_dir=None)
    assert found == [img.resolve()]


def test_extract_workspace_relative_path(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    img = ws / "out" / "result.png"
    img.parent.mkdir()
    img.write_bytes(b"data")
    text = "생성된 파일: out/result.png"
    found = extract_artifacts(text, workspace_dir=str(ws))
    assert found == [img.resolve()]


def test_extract_path_from_markdown_link(tmp_path):
    doc = tmp_path / "draft.md"
    doc.write_text("# draft")
    text = f"작성했습니다: [draft.md]({doc})"
    found = extract_artifacts(text, workspace_dir=None)
    assert found == [doc.resolve()]


def test_extract_json_review_document(tmp_path):
    doc = tmp_path / "theology.review.json"
    doc.write_text('{"schema":"kairos.theology-review.v1"}', encoding="utf-8")
    text = f"승인 검토: {doc}"
    found = extract_artifacts(text, workspace_dir=None)
    assert found == [doc.resolve()]


def test_extract_skips_missing_file(tmp_path):
    text = "없는 파일: /nope/not-there.png 그리고 also-missing.md"
    found = extract_artifacts(text, workspace_dir=str(tmp_path))
    assert found == []


def test_collect_creates_parts_with_image_and_document_types(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    img = tmp_path / "pic.png"
    img.write_bytes(b"pngbytes")
    doc = tmp_path / "notes.md"
    doc.write_text("# hello")
    text = f"이미지 {img} 그리고 문서 {doc}"
    parts = collect(text, workspace_dir=None, data_dir=data_dir, message_id=42)
    assert len(parts) == 2
    types = {p["type"] for p in parts}
    assert types == {"image", "document"}
    for p in parts:
        assert p["artifact"].startswith("42/")
        copied = data_dir / "artifacts" / p["artifact"]
        assert copied.is_file()
    doc_part = next(p for p in parts if p["type"] == "document")
    assert doc_part["title"] == "notes.md"


def test_collect_skips_oversized_file(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    big = tmp_path / "huge.png"
    big.write_bytes(b"0" * (11 * 1024 * 1024))
    small = tmp_path / "small.png"
    small.write_bytes(b"ok")
    text = f"{big} {small}"
    parts = collect(text, workspace_dir=None, data_dir=data_dir, message_id=1)
    assert len(parts) == 1
    assert parts[0]["artifact"] == "1/small.png"


def test_collect_caps_at_six(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    paths = []
    for i in range(8):
        p = tmp_path / f"img{i}.png"
        p.write_bytes(f"x{i}".encode())
        paths.append(str(p))
    text = " ".join(paths)
    parts = collect(text, workspace_dir=None, data_dir=data_dir, message_id=7)
    assert len(parts) == 6


def test_collect_skips_internal_working_files(tmp_path):
    work = tmp_path / "plans"
    (work / "sections").mkdir(parents=True)
    draft = work / "draft.md"
    draft.write_text("# 원고", encoding="utf-8")
    report = work / "gate-report.md"
    report.write_text("# 게이트", encoding="utf-8")
    temp = work / "_sents.md"
    temp.write_text("임시", encoding="utf-8")
    section = work / "sections" / "01_S1.md"
    section.write_text("S1", encoding="utf-8")
    text = f"{draft}\n{report}\n{temp}\n{section}"
    parts = collect(text, None, tmp_path / "data", message_id=1)
    assert [p["title"] for p in parts] == ["draft.md"]


def test_collect_attaches_identical_copies_once(tmp_path):
    work = tmp_path / "plans"
    out = tmp_path / "out"
    work.mkdir()
    out.mkdir()
    draft = work / "draft.md"
    draft.write_text("# 같은 원고", encoding="utf-8")
    copy = out / "2026-10-04_아직-감옥이-끝이-아니다.md"
    copy.write_text("# 같은 원고", encoding="utf-8")
    parts = collect(f"{copy}\n{draft}", None, tmp_path / "data", message_id=1)
    assert [p["title"] for p in parts] == [copy.name]
