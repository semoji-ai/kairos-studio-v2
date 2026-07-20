"""
Bible document store — SQLite FTS5 + bigram search over imported Bible texts, maps, and reference materials.
Separate from chat/feedback history; used for knowledge base retrieval.
"""

import json
import sqlite3
from pathlib import Path
from typing import TypedDict
import logging

log = logging.getLogger(__name__)

class DocumentRecord(TypedDict):
    """A searchable document record."""
    id: str
    source: str  # "bethel", "biblelex", "maps", "commentary", "sermon"
    type: str    # "bible_verse", "commentary", "dictionary", "map", "sermon"
    reference: str  # e.g., "요한복음 3:16" or map title
    content: str  # searchable text
    path: str    # file path or URI if applicable


def create_db(db_path: Path) -> sqlite3.Connection:
    """Create or open the documents database."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Create tables
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            type TEXT NOT NULL,
            reference TEXT,
            content TEXT NOT NULL,
            path TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
            reference, content,
            content=documents, content_rowid=rowid
        )
    """)

    # Create triggers to keep FTS index in sync
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS documents_insert AFTER INSERT ON documents BEGIN
            INSERT INTO documents_fts(rowid, reference, content)
            VALUES (new.rowid, new.reference, new.content);
        END
    """)

    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS documents_delete AFTER DELETE ON documents BEGIN
            DELETE FROM documents_fts WHERE rowid = old.rowid;
        END
    """)

    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS documents_update AFTER UPDATE ON documents BEGIN
            DELETE FROM documents_fts WHERE rowid = old.rowid;
            INSERT INTO documents_fts(rowid, reference, content)
            VALUES (new.rowid, new.reference, new.content);
        END
    """)

    conn.commit()
    return conn


def _bigrams(text: str, max_tokens: int = 64) -> str:
    """
    Convert text to bigrams for FTS5 MATCH query.
    Matches the tokenization in core/recall.py for consistency.
    """
    import re
    token_pattern = re.compile(r"[가-힣A-Za-z0-9]+")
    tokens = token_pattern.findall(text)
    tokens = tokens[:max_tokens]

    if not tokens:
        return ""

    bigrams = []
    for token in tokens:
        for i in range(len(token) - 1):
            bigrams.append(token[i:i+2])

    return " OR ".join(bigrams) if bigrams else ""


def ingest_bible_text(db_path: Path, bible_data_dir: Path) -> int:
    """
    Ingest Bible verses from extracted JSONL files into FTS index.
    Returns count of records added.
    """
    conn = create_db(db_path)
    cursor = conn.cursor()

    record_count = 0
    bible_text_dir = bible_data_dir / "bible_text"

    if not bible_text_dir.exists():
        log.warning(f"Bible text directory not found: {bible_text_dir}")
        return 0

    for jsonl_file in sorted(bible_text_dir.glob("*.jsonl")):
        translation = jsonl_file.stem
        log.info(f"Ingesting {translation} Bible text from {jsonl_file}")

        with open(jsonl_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    record = json.loads(line)
                    doc_id = f"bethel_{translation}_{record['book']}_{record['chapter']}_{record['verse']}"
                    reference = f"{record['book']}:{record['chapter']}:{record['verse']}"
                    content = record['text']

                    cursor.execute("""
                        INSERT OR REPLACE INTO documents
                        (id, source, type, reference, content, path)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        doc_id,
                        "bethel",
                        "bible_verse",
                        reference,
                        content,
                        None
                    ))

                    cursor.execute("""
                        INSERT INTO documents_fts (rowid, reference, content)
                        SELECT rowid, reference, content FROM documents WHERE id = ?
                    """, (doc_id,))

                    record_count += 1

                    if record_count % 10000 == 0:
                        log.debug(f"  ... ingested {record_count} verses")

                except Exception as e:
                    log.error(f"Error ingesting record from {jsonl_file}: {e}")
                    continue

        log.info(f"  ✓ Ingested {record_count} verses from {translation}")

    conn.commit()
    conn.close()
    return record_count


def ingest_mybible_text(db_path: Path, bible_data_dir: Path) -> int:
    """
    Ingest MyBible verses from extracted JSONL file into FTS index.
    Returns count of records added.
    """
    conn = create_db(db_path)
    cursor = conn.cursor()

    record_count = 0
    mybible_dir = bible_data_dir / "mybible"
    mybible_file = mybible_dir / "mybible_bibledb.jsonl"

    if not mybible_file.exists():
        log.warning(f"MyBible JSONL file not found: {mybible_file}")
        return 0

    log.info(f"Ingesting MyBible Bible text from {mybible_file}")

    with open(mybible_file, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                record = json.loads(line)
                # MyBible format: id, book, reference, content, source
                doc_id = f"mybible_{record['id']}"
                book = record.get('book', '')
                reference = f"{book} {record['reference']}"
                content = record['content']

                cursor.execute("""
                    INSERT OR REPLACE INTO documents
                    (id, source, type, reference, content, path)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    doc_id,
                    "mybible",
                    "bible_verse",
                    reference,
                    content,
                    None
                ))

                cursor.execute("""
                    INSERT INTO documents_fts (rowid, reference, content)
                    SELECT rowid, reference, content FROM documents WHERE id = ?
                """, (doc_id,))

                record_count += 1

                if record_count % 500 == 0:
                    log.debug(f"  ... ingested {record_count} MyBible verses")

            except Exception as e:
                log.error(f"Error ingesting MyBible record: {e}")
                continue

    conn.commit()
    conn.close()
    log.info(f"  ✓ Ingested {record_count} MyBible verses")
    return record_count


def ingest_maps(db_path: Path, bible_data_dir: Path) -> int:
    """Ingest Bible map index so they're searchable by title/keywords."""
    conn = create_db(db_path)
    cursor = conn.cursor()

    maps_dir = bible_data_dir / "maps"
    maps_index_file = maps_dir / "maps_index.json"

    if not maps_index_file.exists():
        log.warning(f"Maps index not found: {maps_index_file}")
        return 0

    try:
        with open(maps_index_file, 'r', encoding='utf-8') as f:
            maps = json.load(f)
    except Exception as e:
        log.error(f"Error reading maps index: {e}")
        return 0

    record_count = 0
    for map_entry in maps:
        doc_id = f"map_{map_entry['id']}"
        reference = map_entry.get('title', map_entry.get('filename', ''))
        content = reference  # Searchable text is the title
        path = map_entry.get('path', '')

        try:
            cursor.execute("""
                INSERT OR REPLACE INTO documents
                (id, source, type, reference, content, path)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                doc_id,
                "maps",
                "map",
                reference,
                content,
                path
            ))

            cursor.execute("""
                INSERT INTO documents_fts (rowid, reference, content)
                SELECT rowid, reference, content FROM documents WHERE id = ?
            """, (doc_id,))

            record_count += 1
        except Exception as e:
            log.error(f"Error ingesting map {doc_id}: {e}")

    conn.commit()
    log.info(f"✓ Ingested {record_count} map entries")
    conn.close()
    return record_count


def search(db_path: Path, query: str, limit: int = 5) -> list[DocumentRecord]:
    """
    Search documents using FTS5 bigram matching.
    Returns up to `limit` most relevant records.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Build FTS MATCH query using bigrams
    bigram_query = _bigrams(query)
    if not bigram_query:
        log.warning(f"No searchable terms in query: {query}")
        conn.close()
        return []

    try:
        # FTS5 BM25 ranking: higher score = better match
        sql = f"""
            SELECT d.id, d.source, d.type, d.reference, d.content, d.path
            FROM documents d
            JOIN documents_fts fts ON d.rowid = fts.rowid
            WHERE documents_fts MATCH ?
            ORDER BY bm25(documents_fts, 10.0, 5.0) ASC
            LIMIT ?
        """
        cursor.execute(sql, (bigram_query, limit))
        results = [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        log.error(f"Search error: {e}")
        results = []
    finally:
        conn.close()

    return results


def populate_knowledge_base(db_path: Path, bible_data_dir: Path) -> dict:
    """
    Full pipeline to ingest all available Bible data into the knowledge base.
    Returns summary of what was ingested.
    """
    log.info("=" * 60)
    log.info("Building Bible Knowledge Base (FTS5 index)")
    log.info("=" * 60)

    # Ensure DB exists
    create_db(db_path)

    # Ingest Bible texts (Bethlehem)
    bible_count = ingest_bible_text(db_path, bible_data_dir)

    # Ingest MyBible texts
    mybible_count = ingest_mybible_text(db_path, bible_data_dir)

    # Ingest maps
    maps_count = ingest_maps(db_path, bible_data_dir)

    summary = {
        "bethel_verses": bible_count,
        "mybible_verses": mybible_count,
        "maps": maps_count,
        "total": bible_count + mybible_count + maps_count,
        "db_path": str(db_path)
    }

    log.info("=" * 60)
    log.info(f"Knowledge Base Summary:")
    log.info(f"  Bethlehem Bible verses: {bible_count:,}")
    log.info(f"  MyBible verses: {mybible_count:,}")
    log.info(f"  Maps: {maps_count}")
    log.info(f"  Total indexed: {summary['total']:,}")
    log.info(f"  Database: {db_path}")
    log.info("=" * 60)

    return summary


if __name__ == "__main__":
    # Quick test
    import sys
    logging.basicConfig(level=logging.INFO)

    project_root = Path(__file__).parent.parent
    db_path = project_root / "bible_documents.db"
    bible_data_dir = project_root / "bible_data"

    summary = populate_knowledge_base(db_path, bible_data_dir)

    # Test search
    print("\nTest searches:")
    for test_query in ["요한복음", "예수님", "창조", "팔레스타인"]:
        results = search(db_path, test_query, limit=3)
        print(f"\n  Query: '{test_query}' → {len(results)} results")
        for r in results[:2]:
            print(f"    - {r['reference']}: {r['content'][:60]}...")

    sys.exit(0)
