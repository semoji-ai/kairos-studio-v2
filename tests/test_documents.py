"""Tests for Bible documents module."""

import json
import os
import sys
from pathlib import Path
import sqlite3
import pytest

from core import documents


@pytest.fixture
def test_db():
    """Create a temporary test database."""
    db_path = Path("test_documents.db")
    try:
        if db_path.exists():
            db_path.unlink()
    except PermissionError:
        pass  # Previous test left it locked
    yield db_path
    # Cleanup: close any open connections first
    try:
        if db_path.exists():
            db_path.unlink()
    except PermissionError:
        pass  # File locked, will be cleaned up next run


def test_create_db(test_db):
    """Test database creation."""
    conn = documents.create_db(test_db)
    cursor = conn.cursor()

    # Check tables exist
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}

    assert "documents" in tables
    assert "documents_fts" in tables
    conn.close()


def test_search_empty(test_db):
    """Test search on empty database."""
    documents.create_db(test_db)
    results = documents.search(test_db, "test query")

    assert results == []


def test_search_with_data(test_db):
    """Test search with actual data."""
    conn = documents.create_db(test_db)
    cursor = conn.cursor()

    # Insert test records (triggers auto-update FTS)
    test_records = [
        ("ref1", "요한복음 3:16", "하나님이 세상을 이처럼 사랑하사 독생자를 주셨으니", None),
        ("ref2", "요한복음 3:17", "하나님이 그 아들을 세상에 보내신 것은", None),
        ("ref3", "창세기 1:1", "태초에 하나님이 천지를 창조하시니라", None),
    ]

    for doc_id, reference, content, path in test_records:
        cursor.execute("""
            INSERT INTO documents (id, source, type, reference, content, path)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (doc_id, "bethel", "bible_verse", reference, content, path))

    conn.commit()
    conn.close()

    # Test search
    results = documents.search(test_db, "요한복음", limit=2)

    assert len(results) >= 1
    # Check that at least one result contains the search term
    assert any("요한" in r.get("reference", "") or "요한" in r.get("content", "") for r in results)


def test_bigrams_tokenization():
    """Test bigram tokenization."""
    from core.documents import _bigrams

    # Korean text
    result = _bigrams("요한복음")
    assert "요한" in result
    assert "한복" in result
    assert "복음" in result

    # Empty text
    assert _bigrams("") == ""

    # Single character
    result = _bigrams("a")
    assert result == ""  # No bigrams from single char


def test_knowledge_base_population():
    """Test full knowledge base population (if Bible data exists)."""
    project_root = Path(__file__).parent.parent
    bible_data_dir = project_root / "bible_data"

    if not bible_data_dir.exists():
        pytest.skip("Bible data not extracted")

    db_path = project_root / "test_bible_kb.db"
    if db_path.exists():
        db_path.unlink()

    try:
        summary = documents.populate_knowledge_base(db_path, bible_data_dir)

        assert summary["bethel_verses"] > 0 or summary["mybible_verses"] > 0
        assert summary["total"] > 0

        # Test search
        results = documents.search(db_path, "창조", limit=1)
        assert len(results) > 0

        # Print summary
        print(f"\n[OK] Knowledge Base Population Test:")
        print(f"  Bethlehem verses: {summary.get('bethel_verses', 0):,}")
        print(f"  MyBible verses: {summary.get('mybible_verses', 0):,}")
        print(f"  Maps: {summary.get('maps', 0)}")
        print(f"  Total: {summary['total']:,}")

    finally:
        try:
            if db_path.exists():
                db_path.unlink()
        except PermissionError:
            pass


# --- 장절 참조 정규화 -------------------------------------------------------


def test_ref_key_handles_every_ingest_format():
    """인제스트 경로마다 다른 표기가 하나의 canonical 키로 모여야 한다."""
    assert documents.ref_key("43:3:16") == "43:3:16"        # bethel
    assert documents.ref_key("요한복음 3:16") == "43:3:16"   # mybible
    assert documents.ref_key("요 3:16") == "43:3:16"         # 약어
    assert documents.ref_key("kwanju_43003016") == "43:3:16"  # 관주 앵커
    assert documents.ref_key("창세기 1장 1절") == "1:1:1"


def test_ref_key_rejects_non_references():
    for junk in ["", "   ", "G4982", "구원", "map_detailed_20240115", "99:1:1"]:
        assert documents.ref_key(junk) is None, junk


def test_parse_refs_continues_book_and_expands_range():
    refs = documents.parse_refs("창1:1; 2:4, 요1:1-3")
    # "2:4"는 책 이름이 생략됐으므로 직전 책(창세기)을 잇는다
    assert refs == ["1:1:1", "1:2:4", "43:1:1", "43:1:2", "43:1:3"]


def test_parse_refs_ignores_bare_numbers_without_book():
    """책 이름이 한 번도 없으면 숫자쌍을 장절로 오인하지 않는다."""
    assert documents.parse_refs("비율은 3:1, 2:4 입니다") == []


def test_parse_refs_caps_long_ranges():
    assert len(documents.parse_refs("시119:1-176")) == documents.VERSE_RANGE_CAP


# --- 관주 그래프 -------------------------------------------------------------


def _insert(cursor, doc_id, doc_type, reference, content):
    cursor.execute(
        "INSERT INTO documents (id, source, type, reference, content, path)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (doc_id, "test", doc_type, reference, content, None),
    )


@pytest.fixture
def linked_db(tmp_path):
    """어휘가 겹치지 않지만 관주로 이어진 두 구절 + 관주 레코드."""
    db_path = tmp_path / "linked.db"
    conn = documents.create_db(db_path)
    cursor = conn.cursor()
    _insert(cursor, "v_eph", "bible_verse", "49:2:8",
            "너희는 그 은혜에 의하여 믿음으로 말미암아 구원을 받았으니")
    _insert(cursor, "v_rom", "bible_verse", "45:3:24",
            "그리스도 예수 안에 있는 속량으로 말미암아 값 없이 의롭다 하심을 얻은 자 되었느니라")
    _insert(cursor, "v_other", "bible_verse", "1:1:1",
            "태초에 하나님이 천지를 창조하시니라")
    _insert(cursor, "kw", "cross_reference", "kwanju_49002008", "롬3:24")
    conn.commit()
    conn.close()
    return db_path


def test_rebuild_verse_index_builds_links(linked_db):
    stats = documents.rebuild_verse_index(linked_db)

    assert stats["verse_links"] == 1
    assert stats["unresolved_anchors"] == 0
    # cross_reference 문서 자신은 장절 매핑에 들어가지 않는다
    assert stats["verse_refs"] == 3

    conn = sqlite3.connect(str(linked_db))
    rows = conn.execute("SELECT from_ref, to_ref FROM verse_links").fetchall()
    conn.close()
    assert rows == [("49:2:8", "45:3:24")]


def test_rebuild_verse_index_reports_unresolved_anchors(tmp_path):
    db_path = tmp_path / "bad.db"
    conn = documents.create_db(db_path)
    _insert(conn.cursor(), "kw", "cross_reference", "정체불명앵커", "롬3:24")
    conn.commit()
    conn.close()

    stats = documents.rebuild_verse_index(db_path)

    assert stats["verse_links"] == 0
    assert stats["unresolved_anchors"] == 1
    assert stats["unresolved_anchor_samples"] == ["정체불명앵커"]


def test_rebuild_verse_index_is_idempotent(linked_db):
    first = documents.rebuild_verse_index(linked_db)
    second = documents.rebuild_verse_index(linked_db)
    assert first["verse_links"] == second["verse_links"]
    assert first["verse_refs"] == second["verse_refs"]


def test_search_surfaces_cross_referenced_verse(linked_db):
    """어휘가 안 겹치는 구절이 관주 링크를 타고 올라온다 — 시맨틱의 핵심 이득."""
    documents.rebuild_verse_index(linked_db)

    lexical_only = documents.search(linked_db, "은혜 믿음 구원", limit=3,
                                    expand_links=False)
    assert "v_rom" not in {r["id"] for r in lexical_only}

    expanded = documents.search(linked_db, "은혜 믿음 구원", limit=3)
    ids = [r["id"] for r in expanded]
    assert "v_eph" == ids[0]      # 어휘로 직접 매칭된 구절이 여전히 1위
    assert "v_rom" in ids         # 관주로 이어진 구절이 새로 진입


def test_search_without_links_keeps_bm25_order(linked_db):
    """링크 테이블이 비어 있으면 기존 BM25 동작과 동일해야 한다 (하위호환)."""
    before = documents.search(linked_db, "구원", limit=3)
    documents.rebuild_verse_index(linked_db)
    after = documents.search(linked_db, "구원", limit=3, expand_links=False)
    assert [r["id"] for r in before] == [r["id"] for r in after]


def _legacy_db(path):
    """이 변경 이전에 구워진 bible_documents.db 재현 — 관주 인덱스가 없다.

    번들 DB는 빌드 타임 자산이라 코드보다 오래된 판이 배포돼 있을 수 있다.
    """
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE documents (
            id TEXT PRIMARY KEY, source TEXT NOT NULL, type TEXT NOT NULL,
            reference TEXT, content TEXT NOT NULL, path TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP)
    """)
    cur.execute("""
        CREATE VIRTUAL TABLE documents_fts USING fts5(
            reference, content, content=documents, content_rowid=rowid)
    """)
    cur.execute(
        "INSERT INTO documents (id, source, type, reference, content)"
        " VALUES ('v1','bethel','bible_verse','43:3:16','하나님이 세상을 이처럼 사랑하사')"
    )
    cur.execute(
        "INSERT INTO documents_fts (rowid, reference, content)"
        " SELECT rowid, reference, content FROM documents"
    )
    conn.commit()
    conn.close()
    return path


def test_search_falls_back_when_verse_index_missing(tmp_path):
    """관주 테이블이 없는 구버전 DB에서도 BM25 결과는 살아야 한다.

    번들 DB와 코드는 따로 갱신되므로, 확장 실패로 검색이 통째로 빈손이 되면
    구버전 DB가 깔린 설치본의 성경 검색이 전부 죽는다.
    """
    db_path = _legacy_db(tmp_path / "legacy.db")

    results = documents.search(db_path, "하나님 사랑", limit=3)

    assert [r["id"] for r in results] == ["v1"]


def test_search_falls_back_with_feedback_on_legacy_db(tmp_path):
    db_path = _legacy_db(tmp_path / "legacy_fb.db")

    results = documents.search(db_path, "하나님 사랑", limit=3,
                               ref_feedback={"43:3:16": {"up": 1, "down": 0}})

    assert [r["id"] for r in results] == ["v1"]


def test_has_verse_index_detects_both_tables(tmp_path):
    legacy = sqlite3.connect(str(_legacy_db(tmp_path / "detect.db")))
    assert documents._has_verse_index(legacy.cursor()) is False
    legacy.close()

    fresh = documents.create_db(tmp_path / "fresh.db")
    assert documents._has_verse_index(fresh.cursor()) is True
    fresh.close()


# --- 시작 시 자동 구축 -------------------------------------------------------


def test_ensure_verse_index_builds_on_legacy_db(tmp_path):
    """git pull로 코드만 받은 머신에서 인덱스가 스스로 지어져야 한다."""
    db_path = _legacy_db(tmp_path / "pulled.db")

    result = documents.ensure_verse_index(db_path)

    assert result["status"] == "rebuilt"
    conn = sqlite3.connect(str(db_path))
    assert documents._has_verse_index(conn.cursor()) is True
    assert documents._stored_index_version(conn.cursor()) == \
        documents.VERSE_INDEX_VERSION
    conn.close()


def test_ensure_verse_index_is_noop_when_current(linked_db):
    documents.rebuild_verse_index(linked_db)

    assert documents.ensure_verse_index(linked_db)["status"] == "current"


def test_ensure_verse_index_rebuilds_on_version_bump(linked_db, monkeypatch):
    documents.rebuild_verse_index(linked_db)
    monkeypatch.setattr(documents, "VERSE_INDEX_VERSION",
                        documents.VERSE_INDEX_VERSION + 1)

    assert documents.ensure_verse_index(linked_db)["status"] == "rebuilt"


def test_ensure_verse_index_without_db_is_safe(tmp_path):
    assert documents.ensure_verse_index(tmp_path / "없음.db") == {"status": "no_db"}


def test_ensure_verse_index_survives_unwritable_db(tmp_path, monkeypatch):
    """설치된 번들처럼 쓸 수 없으면 조용히 건너뛰고 검색은 그대로 동작한다.

    권한 대신 쓰기 실패를 직접 주입한다 — root로 도는 CI나 권한 모델이 다른
    OS에서도 같은 경로를 검증하기 위해.
    """
    db_path = _legacy_db(tmp_path / "unwritable.db")

    def _readonly(*args, **kwargs):
        raise sqlite3.OperationalError("attempt to write a readonly database")

    monkeypatch.setattr(documents, "rebuild_verse_index", _readonly)

    result = documents.ensure_verse_index(db_path)

    assert result["status"] == "unwritable"
    # 인덱스가 없어도 BM25 검색은 살아 있다
    assert [r["id"] for r in documents.search(db_path, "하나님 사랑")] == ["v1"]


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root는 파일 권한을 무시한다",
)
@pytest.mark.skipif(sys.platform == "win32",
                    reason="POSIX 권한 비트가 없다")
def test_ensure_verse_index_survives_readonly_file(tmp_path):
    """실제 읽기 전용 파일에서도 기동을 막지 않는다."""
    db_path = _legacy_db(tmp_path / "readonly.db")
    db_path.chmod(0o444)
    try:
        assert documents.ensure_verse_index(db_path)["status"] == "unwritable"
    finally:
        db_path.chmod(0o644)


def test_default_db_path_sits_next_to_core():
    path = documents.default_db_path()
    assert path.name == "bible_documents.db"
    assert path.parent == Path(documents.__file__).resolve().parent.parent


# --- 피드백 가중 -------------------------------------------------------------


def test_feedback_multiplier_matches_recall_scale():
    assert documents.feedback_multiplier(0, 0) == 1.0
    assert documents.feedback_multiplier(1, 0) == 1.5   # recall.py의 up ×1.5
    assert documents.feedback_multiplier(0, 1) == 0.5
    # 상·하한으로 클램프되어 폭주하지 않는다
    assert documents.feedback_multiplier(100, 0) == documents.FEEDBACK_MAX
    assert documents.feedback_multiplier(0, 100) == documents.FEEDBACK_MIN


def test_search_feedback_promotes_liked_verse(tmp_path):
    db_path = tmp_path / "fb.db"
    conn = documents.create_db(db_path)
    cursor = conn.cursor()
    # 같은 낱말을 담아 BM25 점수가 비슷하게 나오는 두 구절
    _insert(cursor, "v_a", "bible_verse", "45:3:24", "값 없이 의롭다 하심을 얻은 자")
    _insert(cursor, "v_b", "bible_verse", "49:2:8", "믿음으로 말미암아 구원을 받았으니")
    conn.commit()
    conn.close()

    query = "믿음 구원 의롭다"
    baseline = documents.search(db_path, query, limit=2)
    assert len(baseline) == 2
    loser = baseline[-1]

    boosted = documents.search(
        db_path, query, limit=2,
        ref_feedback={loser["reference"]: {"up": 3, "down": 0}},
    )
    assert boosted[0]["id"] == loser["id"]


def test_search_feedback_reaches_other_source_notation(tmp_path):
    """'요한복음 3:16'으로 남긴 평가가 '43:3:16' 표기 문서에도 닿아야 한다."""
    db_path = tmp_path / "notation.db"
    conn = documents.create_db(db_path)
    cursor = conn.cursor()
    _insert(cursor, "v_num", "bible_verse", "43:3:16", "하나님이 세상을 이처럼 사랑하사")
    _insert(cursor, "v_dec", "bible_verse", "43:3:17", "하나님이 그 아들을 세상에 보내신 것은")
    conn.commit()
    conn.close()

    down_ranked = documents.search(
        db_path, "하나님이 세상을", limit=2,
        ref_feedback={"요한복음 3:16": {"up": 0, "down": 4}},
    )
    assert down_ranked[-1]["id"] == "v_num"


def test_search_feedback_does_not_mutate_caller_dict(tmp_path):
    db_path = tmp_path / "nomutate.db"
    conn = documents.create_db(db_path)
    _insert(conn.cursor(), "v", "bible_verse", "43:3:16", "하나님이 세상을 사랑하사")
    conn.commit()
    conn.close()

    feedback = {"요한복음 3:16": {"up": 1, "down": 0}}
    documents.search(db_path, "하나님", limit=1, ref_feedback=feedback)
    assert feedback == {"요한복음 3:16": {"up": 1, "down": 0}}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
