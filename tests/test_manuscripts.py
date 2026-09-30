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


# ── 최종 리뷰 지적 재현 ─────────────────────────────────────


def test_corrupt_document_marks_error_without_losing_batch(tmp_path):
    ws = _ws(tmp_path)
    res = ms.stage_upload(ws, [("망가진.docx", b"not a zip"),
                               ("정상.md", ("# 설교\n\n" + LONG).encode())])
    st = {i["name"]: i["status"] for i in res["items"]}
    assert st == {"망가진.docx": "error", "정상.md": "ok"}


def test_same_day_same_filename_keeps_both_originals(tmp_path):
    ws = _ws(tmp_path)
    for body in ["첫째 " + LONG, "둘째 " + LONG]:
        up = ms.stage_upload(ws, [("설교.md", ("# 설교\n\n" + body).encode())])
        ms.commit_upload(ws, up["upload_id"], [
            {"name": "설교.md", "title": "설교", "type": "primary", "include": True}],
            today=date(2026, 9, 30))
    entries = sorted((ws / "raw" / "entries").iterdir())
    paths = [_front(p)["source_path"] for p in entries]
    assert len(set(paths)) == 2
    assert "첫째" in (ws / paths[0]).read_text(encoding="utf-8")
    assert "둘째" in (ws / paths[1]).read_text(encoding="utf-8")


def test_commit_creates_entries_dir_and_rolls_back_on_failure(tmp_path, monkeypatch):
    ws = _ws(tmp_path)
    (ws / "raw" / "entries").rmdir()
    up = ms.stage_upload(ws, [("a.md", ("# A\n\n" + LONG).encode())])
    choice = [{"name": "a.md", "title": "A", "type": "primary", "include": True}]

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(ms.shutil, "move", boom)
    with pytest.raises(OSError):
        ms.commit_upload(ws, up["upload_id"], choice, today=date(2026, 9, 30))
    assert not list((ws / "raw" / "entries").glob("*.md"))  # 반쯤 쓴 기록 없음
    monkeypatch.undo()
    res = ms.commit_upload(ws, up["upload_id"], choice, today=date(2026, 9, 30))
    assert res["source_ids"] == ["src_20260930_001"]


def test_pdf_page_markers_are_not_titles_or_split_points(tmp_path):
    ws = _ws(tmp_path)
    pages = "\n\n".join(f"## 원본 {n}쪽\n" + "\n".join(f"{n}쪽 {j}번째 문장입니다." for j in range(40))
                        for n in range(1, 16))  # 약 630줄, 쪽 표시 15개
    up = ms.stage_upload(ws, [("강해.md", pages.encode())])
    assert up["items"][0]["title"] != "원본 1쪽"
    res = ms.commit_upload(ws, up["upload_id"], [
        {"name": "강해.md", "title": "강해", "type": "primary", "include": True}],
        today=date(2026, 9, 30))
    assert 2 <= len(res["source_ids"]) <= 3  # 쪽마다 쪼개지지 않음
