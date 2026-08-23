"""
Bible document store — SQLite FTS5 + bigram search over imported Bible texts, maps, and reference materials.
Separate from chat/feedback history; used for knowledge base retrieval.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import TypedDict
import logging

from core import bible_coverage

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

    # 관주(cross_reference) 그래프. from_ref → to_ref 는 사람이 검증해 놓은
    # 의미 링크라, 임베딩 없이도 "표층 글자는 다르지만 뜻이 이어지는 구절"을
    # 찾는 확장 경로가 된다.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS verse_links (
            from_ref TEXT NOT NULL,
            to_ref TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'kwanju',
            PRIMARY KEY (from_ref, to_ref, source)
        ) WITHOUT ROWID
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_verse_links_from ON verse_links(from_ref)"
    )

    # canonical 장절 키 → 문서. documents.reference 표기가 소스마다 달라
    # (숫자 책번호 / 한글 책이름) 조인 키를 따로 물질화해 둔다.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS verse_refs (
            ref_key TEXT NOT NULL,
            doc_id TEXT NOT NULL,
            PRIMARY KEY (ref_key, doc_id)
        ) WITHOUT ROWID
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_verse_refs_doc ON verse_refs(doc_id)"
    )

    # 인덱스 판 버전. bible_documents.db는 gitignore라 git pull로 갱신되지
    # 않으므로, 코드가 올라갔을 때 낡은 인덱스를 스스로 알아보고 다시 지어야
    # 한다. 링크 생성 규칙이 바뀌면 VERSE_INDEX_VERSION을 올린다.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS verse_index_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
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

    # FTS5 unicode61 인덱스는 어절 단위 통짜 토큰이라 순수 바이그램은 매치되지
    # 않는다 ("요한복음" 토큰 vs "요한" 쿼리). 접두사 질의(토큰* / 바이그램*)로
    # 부분 일치를 잡는다.
    terms = []
    seen = set()
    for token in tokens:
        if len(token) < 2:  # 한 글자 토큰은 기존 계약대로 검색어를 만들지 않는다
            continue
        for cand in [token] + [token[i:i + 2] for i in range(len(token) - 1)]:
            if cand not in seen:
                seen.add(cand)
                terms.append(f'"{cand}"*')

    return " OR ".join(terms) if terms else ""


# --- 장절 참조 정규화 -------------------------------------------------------
# 인제스트 경로마다 reference 표기가 다르다: bethel은 "43:3:16"(숫자 책번호),
# MyBible은 "요한복음 3:16", 관주 앵커는 "kwanju_43003016" 같은 압축 코드.
# 관주 링크를 이으려면 이 셋을 하나의 canonical key로 모아야 한다.

_BOOK_ALT = "|".join(re.escape(b) for b in bible_coverage.book_tokens())
# 책 이름이 반드시 있는 단일 참조용 (ref_key)
_REF_RE = re.compile(
    r"(" + _BOOK_ALT + r")\s*(\d{1,3})\s*[:：장]\s*(\d{1,3})"
    r"(?:\s*[-~–]\s*(\d{1,3}))?"
)
# 자유 본문 스캔용 — 책 이름 생략 시 직전 책을 잇는다 ("창1:1; 2:4")
_REF_SCAN_RE = re.compile(
    r"(?:(" + _BOOK_ALT + r")\s*)?(\d{1,3})\s*[:：장]\s*(\d{1,3})"
    r"(?:\s*[-~–]\s*(\d{1,3}))?"
)
_NUMERIC_REF_RE = re.compile(r"^(\d{1,2})[:\s](\d{1,3})[:\s](\d{1,3})$")
_PACKED_REF_RE = re.compile(r"^(?:[A-Za-z_]*_)?(\d{2})(\d{3})(\d{3})$")

# 한 참조에서 펼칠 최대 절 수. "시119:1-176" 같은 범위가 링크 테이블을
# 폭발시키지 않게 자른다.
VERSE_RANGE_CAP = 30


# 관주 인덱스 판 버전 — 링크 생성 규칙이 바뀌면 올린다. 시작 시 저장된 값과
# 다르면 자동으로 다시 짓는다.
VERSE_INDEX_VERSION = 1


def default_db_path() -> Path:
    """번들·체크아웃 양쪽에서 통하는 성경 DB 위치.

    개발 체크아웃에서는 core/ 옆의 리포 루트, 릴리스 번들에서는 core/가
    resources/core/ 이므로 resources/bible_documents.db 로 같이 풀린다.
    """
    return Path(__file__).resolve().parent.parent / "bible_documents.db"


# 개역개정 실측 최대치. 책별 정확한 절 수 검증은 워크스페이스 데이터가 있어야
# 하므로, 여기서는 명백한 오탐(파일명 숫자 등)만 걸러내는 상한으로 쓴다.
MAX_CHAPTER = 150
MAX_VERSE = 176


def _key(book: int, chapter: int, verse: int) -> str | None:
    if not 1 <= book <= len(bible_coverage.BOOKS):
        return None
    if not 1 <= chapter <= MAX_CHAPTER:
        return None
    if not 1 <= verse <= MAX_VERSE:
        return None
    return bible_coverage.verse_key(book, chapter, verse)


def ref_key(reference: str) -> str | None:
    """단일 참조 문자열 → canonical "책번호:장:절". 해석 불가면 None."""
    text = (reference or "").strip()
    if not text:
        return None

    m = _NUMERIC_REF_RE.match(text)
    if m:
        return _key(*(int(x) for x in m.groups()))

    m = _REF_RE.search(text)
    if m:
        book = bible_coverage.book_num(m.group(1))
        if book:
            return _key(book, int(m.group(2)), int(m.group(3)))

    m = _PACKED_REF_RE.search(text)
    if m:
        return _key(*(int(x) for x in m.groups()))

    return None


def parse_refs(text: str, cap: int = VERSE_RANGE_CAP) -> list[str]:
    """자유 본문에서 장절 참조를 모두 뽑아 canonical key 리스트로.

    책 이름이 생략된 참조는 같은 본문에서 직전에 나온 책을 잇는다. 책 이름이
    한 번도 나오지 않았다면 맨 숫자쌍은 참조로 보지 않는다 (오탐 방지).
    """
    out: list[str] = []
    seen: set[str] = set()
    current_book: int | None = None

    for m in _REF_SCAN_RE.finditer(text or ""):
        name = m.group(1)
        if name:
            book = bible_coverage.book_num(name)
            if book:
                current_book = book
        if current_book is None:
            continue

        chapter, start = int(m.group(2)), int(m.group(3))
        end = int(m.group(4)) if m.group(4) else start
        if end < start:
            end = start
        end = min(end, start + cap - 1)

        for verse in range(start, end + 1):
            key = _key(current_book, chapter, verse)
            if key and key not in seen:
                seen.add(key)
                out.append(key)

    return out


def _stored_index_version(cursor) -> int | None:
    try:
        row = cursor.execute(
            "SELECT value FROM verse_index_meta WHERE key='version'"
        ).fetchone()
    except sqlite3.Error:
        return None  # 메타 테이블 자체가 없는 구판
    if row is None:
        return None
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return None


def ensure_verse_index(db_path: Path) -> dict:
    """관주 인덱스가 최신이 아니면 다시 짓는다. 서버 시작 시 1회 호출.

    bible_documents.db는 gitignore라 git pull로 갱신되지 않는다 — 각 머신이
    로컬에서 구운 사본을 갖고 있다. 그래서 코드만 새로 받으면 인덱스는 낡은
    채로 남고, 사용자가 스크립트를 손수 돌려야 하는 상황이 된다. 여기서 스스로
    알아보고 짓게 해 pull 한 번으로 끝나게 한다.

    설치된 앱 번들처럼 DB가 읽기 전용이면 조용히 건너뛴다 — 그쪽은 빌드 타임에
    이미 구워져 나온다. 어느 경우든 실패가 앱 기동을 막지 않는다.
    """
    path = Path(db_path)
    if not path.is_file():
        return {"status": "no_db"}

    try:
        conn = sqlite3.connect(str(path))
        try:
            cursor = conn.cursor()
            if (_has_verse_index(cursor)
                    and _stored_index_version(cursor) == VERSE_INDEX_VERSION):
                return {"status": "current"}
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.warning(f"verse index check failed: {exc}")
        return {"status": "error", "error": str(exc)}

    try:
        stats = rebuild_verse_index(path)
    except sqlite3.Error as exc:
        # 읽기 전용 번들이 여기로 온다. 확장만 없을 뿐 BM25 검색은 그대로다.
        log.warning(f"verse index rebuild skipped (read-only?): {exc}")
        return {"status": "unwritable", "error": str(exc)}

    log.info(
        "verse index rebuilt on startup: %(verse_links)s links", stats)
    return {"status": "rebuilt", **stats}


def rebuild_verse_index(db_path: Path, sample_limit: int = 10) -> dict:
    """documents 전체를 훑어 verse_refs / verse_links 를 다시 만든다.

    인제스트 경로마다 따로 채우지 않고 한 번에 재구축하는 이유는, 이미 색인이
    끝난 기존 DB에도 재인제스트 없이 적용할 수 있어야 하기 때문이다.

    반환값의 unresolved_* 는 앵커/링크 해석 실패 건수와 그 샘플이다. 관주
    앵커의 표기가 예상과 다르면 여기서 바로 드러난다.
    """
    conn = create_db(db_path)
    cursor = conn.cursor()

    cursor.execute("DELETE FROM verse_refs")
    cursor.execute("DELETE FROM verse_links")

    # ① 장절로 해석되는 모든 문서를 canonical key에 매단다. 성경 본문뿐 아니라
    #    해당 구절 주석도 함께 걸려야 확장의 값어치가 산다.
    ref_rows = 0
    for doc_id, reference in cursor.execute(
        "SELECT id, reference FROM documents WHERE type != 'cross_reference'"
    ).fetchall():
        key = ref_key(reference)
        if key:
            cursor.execute(
                "INSERT OR IGNORE INTO verse_refs (ref_key, doc_id) VALUES (?, ?)",
                (key, doc_id),
            )
            ref_rows += 1

    # ② 관주 레코드: reference가 앵커 구절, content가 관련 구절 목록.
    link_rows = 0
    unresolved_anchors = 0
    unlinked_anchors = 0
    anchor_samples: list[str] = []
    for reference, content in cursor.execute(
        "SELECT reference, content FROM documents WHERE type = 'cross_reference'"
    ).fetchall():
        from_key = ref_key(reference)
        if not from_key:
            unresolved_anchors += 1
            if len(anchor_samples) < sample_limit:
                anchor_samples.append(reference)
            continue
        targets = [k for k in parse_refs(content) if k != from_key]
        if not targets:
            unlinked_anchors += 1
            continue
        for to_key in targets:
            cursor.execute(
                "INSERT OR IGNORE INTO verse_links (from_ref, to_ref, source)"
                " VALUES (?, ?, 'kwanju')",
                (from_key, to_key),
            )
            link_rows += 1

    cursor.execute(
        "INSERT INTO verse_index_meta(key, value) VALUES ('version', ?)"
        " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(VERSE_INDEX_VERSION),),
    )
    conn.commit()

    stats = {
        "verse_refs": cursor.execute(
            "SELECT COUNT(*) FROM verse_refs").fetchone()[0],
        "verse_links": cursor.execute(
            "SELECT COUNT(*) FROM verse_links").fetchone()[0],
        "linked_anchors": cursor.execute(
            "SELECT COUNT(DISTINCT from_ref) FROM verse_links").fetchone()[0],
        "verse_refs_seen": ref_rows,
        "verse_links_seen": link_rows,
        "unresolved_anchors": unresolved_anchors,
        "unlinked_anchors": unlinked_anchors,
        "unresolved_anchor_samples": anchor_samples,
    }
    conn.close()
    log.info(
        "verse index rebuilt: %(verse_refs)s refs, %(verse_links)s links "
        "(unresolved anchors: %(unresolved_anchors)s)", stats
    )
    return stats


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


def ingest_commentary(db_path: Path, bible_data_dir: Path) -> int:
    """
    Ingest commentary and dictionary data from extracted JSONL files.
    Includes: MyBible dicword/dicman/kwanju2, Bethlehem .dct lexicon, detailed maps metadata.
    Returns count of records added.
    """
    conn = create_db(db_path)
    cursor = conn.cursor()

    record_count = 0
    search_dirs = [
        (bible_data_dir / "mybible", "mybible"),
        (bible_data_dir / "bethlehem_commentary", "bethel"),
    ]

    for search_dir, source_prefix in search_dirs:
        if not search_dir.exists():
            continue

        log.info(f"Ingesting commentary from {search_dir}")

        for jsonl_file in sorted(search_dir.glob("*.jsonl")):
            data_type = jsonl_file.stem  # e.g., mybible_dicword, bethel_HebGrkKo_Lexicon

            with open(jsonl_file, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        # Generate unique ID
                        doc_id = f"{source_prefix}_{data_type}_{record.get('id', hash(str(record)))}"

                        # Extract reference and content based on record type
                        if "dicword" in data_type:
                            reference = record.get('word', '')
                            content = record.get('mean', '')
                            doc_type = "dictionary"
                        elif "dicman" in data_type:
                            reference = record.get('item', '')
                            content = f"{record.get('eng', '')} / {record.get('means', '')}"
                            doc_type = "dictionary"
                        elif "kwanju2" in data_type:
                            reference = f"kwanju_{record.get('jj', '')}"
                            content = record.get('ct', '')
                            doc_type = "cross_reference"
                        elif "Lexicon" in data_type:
                            reference = record.get('scode', '')
                            content = record.get('dtext', '')
                            doc_type = "lexicon"
                        else:
                            reference = str(record.get('reference', ''))
                            content = str(record.get('content', ''))
                            doc_type = "commentary"

                        if not content or not reference:
                            continue

                        cursor.execute("""
                            INSERT OR REPLACE INTO documents
                            (id, source, type, reference, content, path)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (
                            doc_id,
                            source_prefix,
                            doc_type,
                            reference[:500],  # Limit reference length
                            content[:8000],   # Limit content length
                            str(jsonl_file)
                        ))

                        cursor.execute("""
                            INSERT INTO documents_fts (rowid, reference, content)
                            SELECT rowid, reference, content FROM documents WHERE id = ?
                        """, (doc_id,))

                        record_count += 1

                        if record_count % 10000 == 0:
                            log.debug(f"  ... ingested {record_count} commentary records")

                    except Exception as e:
                        log.error(f"Error ingesting commentary record: {e}")
                        continue

    conn.commit()
    conn.close()
    log.info(f"  ✓ Ingested {record_count} commentary/dictionary/lexicon records")
    return record_count


def ingest_maps_detailed(db_path: Path, bible_data_dir: Path) -> int:
    """
    Ingest detailed Bible maps metadata with tags and descriptions.
    Returns count of records added.
    """
    conn = create_db(db_path)
    cursor = conn.cursor()

    maps_dir = bible_data_dir / "maps"
    maps_index_file = maps_dir / "maps_detailed_index.jsonl"

    if not maps_index_file.exists():
        log.warning(f"Detailed maps index not found: {maps_index_file}")
        return 0

    log.info(f"Ingesting detailed maps metadata from {maps_index_file}")

    record_count = 0
    try:
        with open(maps_index_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    record = json.loads(line)
                    doc_id = f"map_detailed_{record['id']}"
                    reference = record.get('title', record.get('filename', ''))
                    # Combine title, tags, and filename for searchability
                    tags_str = ' '.join(record.get('tags', []))
                    content = f"{reference} {tags_str}"
                    path = record.get('path', '')

                    cursor.execute("""
                        INSERT OR REPLACE INTO documents
                        (id, source, type, reference, content, path)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        doc_id,
                        "maps",
                        "map_detailed",
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
                    log.error(f"Error ingesting detailed map: {e}")
                    continue

    except Exception as e:
        log.error(f"Error reading maps index: {e}")
        return 0

    conn.commit()
    conn.close()
    log.info(f"  ✓ Ingested {record_count} detailed map entries")
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


# --- 검색 랭킹 상수 ---------------------------------------------------------
# BM25 후보를 넓게 뽑아 두고, 관주 확장과 피드백 가중을 얹어 재랭킹한 뒤 자른다.
POOL_FACTOR = 8
MIN_POOL = 30
# 관주 링크로만 들어온 문서의 감쇠 계수. 1.0 미만이라 어휘 매칭 없이 링크만으로
# 상위를 차지하지는 못하고, BM25로도 걸린 문서가 링크 가점까지 받으면 최상위가
# 된다 — 하이브리드 융합에서 두 랭커가 동의할 때 점수가 몰리는 것과 같은 효과.
LINK_WEIGHT = 0.45
MAX_LINK_SEEDS = 8
MAX_LINKS_PER_SEED = 12
# 피드백 배수 — recall.py의 up ×1.5와 같은 눈금.
FEEDBACK_STEP = 0.5
FEEDBACK_MIN = 0.25
FEEDBACK_MAX = 2.5


def feedback_multiplier(ups: int, downs: int) -> float:
    """up/down 개수 → 점수 배수.

    down을 회상에서처럼 완전 배제하지 않는 이유: 구절 자체가 틀린 게 아니라 그
    구절을 쓴 답변이 거부된 것이다. 배제 대신 가중을 낮춘다.
    """
    mult = 1.0 + FEEDBACK_STEP * ups - FEEDBACK_STEP * downs
    return max(FEEDBACK_MIN, min(FEEDBACK_MAX, mult))


def _has_verse_index(cursor) -> bool:
    """관주 인덱스 테이블이 이 DB에 있는가.

    bible_documents.db는 빌드 타임에 구워져 앱 번들로 배포되는 읽기 전용
    공통 자산이라, 코드보다 오래된 판이 깔려 있을 수 있다. 그럴 때 링크 확장은
    조용히 건너뛰고 BM25 결과는 그대로 살려야 한다.
    """
    rows = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
        " AND name IN ('verse_links','verse_refs')"
    ).fetchall()
    return len(rows) == 2


def _link_expansion(cursor, seed_ids: list[str],
                    seed_scores: dict[str, float]) -> dict[str, float]:
    """상위 BM25 문서에서 관주 링크를 1홉 따라가 {doc_id: 가점}을 만든다."""
    bonus: dict[str, float] = {}
    for doc_id in seed_ids[:MAX_LINK_SEEDS]:
        rows = cursor.execute(
            """
            SELECT DISTINCT tgt.doc_id AS doc_id
            FROM verse_refs src
            JOIN verse_links l ON l.from_ref = src.ref_key
            JOIN verse_refs tgt ON tgt.ref_key = l.to_ref
            WHERE src.doc_id = ? AND tgt.doc_id != ?
            LIMIT ?
            """,
            (doc_id, doc_id, MAX_LINKS_PER_SEED),
        ).fetchall()
        gain = LINK_WEIGHT * seed_scores.get(doc_id, 0.0)
        for row in rows:
            target = row["doc_id"]
            # 여러 시드가 같은 구절을 가리키면 가장 강한 시드 기준으로 한 번만
            # 준다. 합산하면 관주가 촘촘한 구절이 무조건 이긴다.
            if gain > bonus.get(target, 0.0):
                bonus[target] = gain
    return bonus


def search(db_path: Path, query: str, limit: int = 5,
           ref_feedback: dict[str, dict] | None = None,
           expand_links: bool = True) -> list[DocumentRecord]:
    """FTS5 bigram BM25 검색 + 관주 링크 확장 + 피드백 가중 재랭킹.

    ref_feedback: {reference: {"up": n, "down": n}} — store.reference_feedback_weights()
    의 반환값. 과거에 그 구절을 주입한 답변이 받은 평가를 순위에 반영한다.
    두 인자 모두 생략하면 링크·가중 기여가 0이라 기존 BM25 순위와 같다.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    # 인덱스 재구축이 다른 곳에서 돌고 있어도 잠깐 기다렸다 읽는다. 이게 없으면
    # "database is locked"가 아래 except로 떨어져 검색이 빈손이 된다.
    cursor.execute("PRAGMA busy_timeout = 3000")

    # Build FTS MATCH query using bigrams
    bigram_query = _bigrams(query)
    if not bigram_query:
        log.warning(f"No searchable terms in query: {query}")
        conn.close()
        return []

    try:
        # bm25()는 음수가 좋은 점수다(더 작을수록 관련도 높음). ASC 정렬이 맞고,
        # 융합을 위해 부호를 뒤집어 "클수록 좋음"으로 정규화해 쓴다.
        pool = max(MIN_POOL, limit * POOL_FACTOR)
        rows = cursor.execute(
            """
            SELECT d.id, d.source, d.type, d.reference, d.content, d.path,
                   bm25(documents_fts, 10.0, 5.0) AS rank
            FROM documents d
            JOIN documents_fts fts ON d.rowid = fts.rowid
            WHERE documents_fts MATCH ?
            ORDER BY rank ASC
            LIMIT ?
            """,
            (bigram_query, pool),
        ).fetchall()

        if not rows:
            return []

        records: dict[str, dict] = {}
        scores: dict[str, float] = {}
        order: list[str] = []
        best = max(-row["rank"] for row in rows) or 1.0
        for row in rows:
            record = dict(row)
            doc_id = record["id"]
            record.pop("rank", None)
            records[doc_id] = record
            # [0,1] 정규화 — 링크 가점과 같은 눈금에 올린다.
            scores[doc_id] = max(0.0, -row["rank"]) / best
            order.append(doc_id)

        if expand_links and _has_verse_index(cursor):
            # 확장은 부가 기능이다. 여기서 뭐가 터지든 BM25 결과는 살려서
            # 돌려준다 — 검색이 통째로 빈손이 되는 것보다 낫다.
            try:
                bonus = _link_expansion(cursor, order, scores)
                missing = [doc_id for doc_id in bonus if doc_id not in records]
                for chunk_start in range(0, len(missing), 500):
                    chunk = missing[chunk_start:chunk_start + 500]
                    placeholders = ",".join("?" * len(chunk))
                    for row in cursor.execute(
                        f"SELECT id, source, type, reference, content, path"
                        f" FROM documents WHERE id IN ({placeholders})", chunk
                    ).fetchall():
                        records[row["id"]] = dict(row)
                for doc_id, gain in bonus.items():
                    if doc_id in records:
                        scores[doc_id] = scores.get(doc_id, 0.0) + gain
            except sqlite3.Error as exc:
                log.warning(f"link expansion skipped: {exc}")

        if ref_feedback:
            weights = _canonical_feedback(ref_feedback)
            for doc_id, record in records.items():
                reference = record.get("reference") or ""
                # canonical 키를 먼저 본다 — 여러 소스 표기의 피드백이 합쳐진
                # 쪽이라 신호가 더 두껍다. 장절이 아닌 문서(사전 등)는 원 표기로.
                key = ref_key(reference)
                counts = weights.get(key) if key else None
                if counts is None:
                    counts = weights.get(reference)
                if counts:
                    scores[doc_id] *= feedback_multiplier(
                        counts.get("up", 0), counts.get("down", 0))

        ranked = sorted(records, key=lambda i: (-scores.get(i, 0.0), i))
        results = [records[doc_id] for doc_id in ranked[:limit]]
    except Exception as e:
        log.error(f"Search error: {e}")
        results = []
    finally:
        conn.close()

    return results


def _canonical_feedback(ref_feedback: dict[str, dict]) -> dict[str, dict]:
    """피드백 맵에 canonical 장절 키를 덧붙인다.

    같은 구절이라도 소스마다 reference 표기가 다르다("43:3:16" vs "요한복음
    3:16"). 원 표기로 남긴 피드백이 다른 소스의 같은 구절에도 닿게 한다.
    """
    merged: dict[str, dict] = {}
    for reference, counts in ref_feedback.items():
        up, down = counts.get("up", 0), counts.get("down", 0)
        key = ref_key(reference)
        # 원 표기와 canonical 키 양쪽에 싣는다. 둘이 같으면 집합이 한 번만
        # 돌므로 중복 가산되지 않는다. 호출자 dict는 절대 재사용하지 않는다.
        for slot in {reference, key} - {None}:
            acc = merged.setdefault(slot, {"up": 0, "down": 0})
            acc["up"] += up
            acc["down"] += down
    return merged


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

    # Ingest maps (basic)
    maps_count = ingest_maps(db_path, bible_data_dir)

    # Ingest commentary and dictionary data
    commentary_count = ingest_commentary(db_path, bible_data_dir)

    # Ingest detailed maps metadata
    maps_detailed_count = ingest_maps_detailed(db_path, bible_data_dir)

    # 관주 그래프·장절 매핑은 모든 인제스트가 끝난 뒤 한 번에 세운다
    # (관주 앵커가 가리키는 구절 문서가 이미 다 들어와 있어야 한다).
    verse_index = rebuild_verse_index(db_path)

    summary = {
        "bethel_verses": bible_count,
        "mybible_verses": mybible_count,
        "mybible_commentary": commentary_count,
        "maps": maps_count,
        "maps_detailed": maps_detailed_count,
        "total": bible_count + mybible_count + maps_count + commentary_count + maps_detailed_count,
        "verse_refs": verse_index["verse_refs"],
        "verse_links": verse_index["verse_links"],
        "db_path": str(db_path)
    }

    log.info("=" * 60)
    log.info(f"Knowledge Base Summary:")
    log.info(f"  Bethlehem Bible verses: {bible_count:,}")
    log.info(f"  MyBible verses: {mybible_count:,}")
    log.info(f"  MyBible commentary/dictionary: {commentary_count:,}")
    log.info(f"  Maps (basic): {maps_count}")
    log.info(f"  Maps (detailed): {maps_detailed_count}")
    log.info(f"  Total indexed: {summary['total']:,}")
    log.info(f"  Verse refs mapped: {verse_index['verse_refs']:,}")
    log.info(f"  Cross-reference links: {verse_index['verse_links']:,}")
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
