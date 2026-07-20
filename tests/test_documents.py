"""Tests for Bible documents module."""

import json
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
