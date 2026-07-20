#!/usr/bin/env python3
"""
Extract Bible data from accessible sources and normalize into a structured corpus.
"""

import json
import sqlite3
from pathlib import Path
from typing import Generator
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "bible_data"
RAW_DIR = PROJECT_ROOT / "_bible_raw"


def extract_bethel_bible(output_dir: Path) -> int:
    """Extract Bethel (베들레헴) Bible text from SQLite .bdb/.sdb files."""
    output_dir.mkdir(parents=True, exist_ok=True)

    bethel_raw = RAW_DIR / "bethel"
    if not bethel_raw.exists():
        log.warning("Bethel raw dir not found, skipping")
        return 0

    bdb_files = list(bethel_raw.glob("*.bdb")) + list(bethel_raw.glob("*.sdb"))
    log.info(f"Found {len(bdb_files)} Bethel database files")

    count = 0
    for db_file in sorted(bdb_files)[:5]:  # Process first 5 to start
        translation = db_file.stem

        try:
            conn = sqlite3.connect(str(db_file))
            cursor = conn.cursor()

            # Check if Bible table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Bible'")
            if not cursor.fetchone():
                log.warning(f"  {translation}: No 'Bible' table found, skipping")
                continue

            # Extract all verses
            output_file = output_dir / f"{translation}.jsonl"
            with open(output_file, 'w', encoding='utf-8') as out:
                cursor.execute("SELECT id, book, chapter, verse, btext FROM Bible ORDER BY id")
                for row_id, book, chapter, verse, text in cursor.fetchall():
                    record = {
                        "id": row_id,
                        "translation": translation,
                        "book": book,
                        "chapter": chapter,
                        "verse": verse,
                        "text": text,
                        "source": "bethel"
                    }
                    out.write(json.dumps(record, ensure_ascii=False) + "\n")
                    count += 1

            rows_exported = count
            log.info(f"  ✓ {translation}: exported {rows_exported} verses → {output_file}")

            conn.close()
        except Exception as e:
            log.error(f"  ✗ {translation}: {e}")
            continue

    return count


def extract_bethel_commentary(output_dir: Path) -> int:
    """Extract commentary data (if available in searchable form)."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # For now, commentary in the `.cdb` files requires reverse-engineering
    # which is beyond this scope. Log availability but skip extraction.
    log.info("Commentary files (.cdb) found but extraction requires binary format analysis — skipping for now")
    return 0


def copy_bible_maps(source_dir: Path, output_dir: Path) -> int:
    """Copy high-res Bible atlas map images and create index."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Source locations (tried from exploration)
    sources = [
        Path("C:\\Users\\user\\Documents\\0.성경프로그램-지우지마세요\\성경지도모음_고화질"),
        Path("F:\\성경\\성경지도모음_고화질"),
    ]

    source_images = None
    for src in sources:
        if src.exists():
            source_images = src
            break

    if not source_images:
        log.warning("Bible maps folder not found, skipping")
        return 0

    image_files = sorted(source_images.glob("*.jpg"))
    log.info(f"Found {len(image_files)} Bible map images in {source_images}")

    index = []
    for img_path in image_files:
        # Copy image
        dest_img = output_dir / img_path.name
        dest_img.write_bytes(img_path.read_bytes())

        # Parse Korean filename to extract map title
        # Filenames are like: "01.성경지도목차1.jpg", "14.에덴동산,비옥한초승달지역.jpg"
        parts = img_path.stem.split(".", 1)
        number = parts[0]
        title = parts[1] if len(parts) > 1 else img_path.stem

        index.append({
            "id": number,
            "filename": img_path.name,
            "title": title,
            "path": f"bible_data/maps/{img_path.name}",
            "source": "bible_atlas"
        })

        log.debug(f"  Copied: {img_path.name} ({dest_img.stat().st_size / 1e6:.1f} MB)")

    # Save index
    index_file = output_dir / "maps_index.json"
    with open(index_file, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    log.info(f"  ✓ Copied {len(image_files)} images and created index → {index_file}")
    return len(image_files)


def extract_sermons(output_dir: Path) -> int:
    """Extract sermon text from .hwp and .pdf files on Desktop."""
    output_dir.mkdir(parents=True, exist_ok=True)

    sermon_dir = Path.home() / "Desktop"
    sermon_files = list(sermon_dir.glob("*.hwp")) + list(sermon_dir.glob("*.pdf"))

    if not sermon_files:
        log.warning("No sermon files found on Desktop")
        return 0

    log.info(f"Found {len(sermon_files)} potential sermon files on Desktop")

    # Try HWP extraction if python-pptx or similar available
    # For now, just copy file names and note the limitation
    count = 0
    for sermon_file in sorted(sermon_files)[:20]:  # First 20 as sample
        try:
            if sermon_file.suffix.lower() == ".hwp":
                # HWP extraction requires hwp library (not in stdlib)
                # Skip for now, just log
                log.debug(f"  {sermon_file.name} (HWP - requires library, skipping text extraction)")
            elif sermon_file.suffix.lower() == ".pdf":
                # PDF extraction requires PyPDF2 or similar
                log.debug(f"  {sermon_file.name} (PDF - requires library, skipping text extraction)")
            count += 1
        except Exception as e:
            log.error(f"  Error processing {sermon_file.name}: {e}")

    log.info(f"  ✓ Found {count} sermon files (text extraction requires additional libraries)")
    log.info("  → To extract sermon text, install: pip install python-pptx PyPDF2 python-docx")
    return 0  # Return 0 since we haven't extracted yet


def main():
    log.info("=" * 60)
    log.info("Bible Data Extraction Pipeline")
    log.info("=" * 60)

    # Create main data directory
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Phase 2.1: Extract Bible text
    log.info("\n[Phase 2.1] Extracting Bible text from Bethel...")
    bible_text_dir = DATA_DIR / "bible_text"
    bethel_count = extract_bethel_bible(bible_text_dir)

    # Phase 2.2: Extract commentary (placeholder)
    log.info("\n[Phase 2.2] Extracting commentary...")
    commentary_count = extract_bethel_commentary(DATA_DIR / "commentary")

    # Phase 2.3: Copy maps
    log.info("\n[Phase 2.3] Copying Bible maps...")
    maps_count = copy_bible_maps(None, DATA_DIR / "maps")

    # Phase 2.4: Extract sermons
    log.info("\n[Phase 2.4] Extracting sermons...")
    sermon_count = extract_sermons(DATA_DIR / "sermons")

    log.info("\n" + "=" * 60)
    log.info("Summary")
    log.info("=" * 60)
    log.info(f"Bible verses: {bethel_count:,}")
    log.info(f"Commentary records: {commentary_count}")
    log.info(f"Map images: {maps_count}")
    log.info(f"Sermon files: {sermon_count}")
    log.info(f"Output directory: {DATA_DIR}")
    log.info("=" * 60)

    return 0 if bethel_count > 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
