#!/usr/bin/env python3
"""Test script to check if Bible app databases can be read."""

import sqlite3
import sys
from pathlib import Path

def test_sqlite_file(fpath):
    """Try to open a file as SQLite and report findings."""
    print(f"\n{'='*60}")
    print(f"Testing: {fpath.name} ({fpath.stat().st_size / 1e6:.2f} MB)")
    print('='*60)

    # Read first few bytes to check magic number
    with open(fpath, 'rb') as f:
        header = f.read(16)

    if header.startswith(b'SQLite format 3'):
        print("✓ Header: SQLite format 3 detected")

        try:
            conn = sqlite3.connect(str(fpath))
            cursor = conn.cursor()

            # Get table names
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 20")
            tables = [row[0] for row in cursor.fetchall()]
            print(f"✓ Opened successfully. Tables ({len(tables)}):")
            for table in tables[:10]:
                print(f"  - {table}")
            if len(tables) > 10:
                print(f"  ... and {len(tables)-10} more")

            # Sample the first table
            if tables:
                first_table = tables[0]
                cursor.execute(f"SELECT COUNT(*) FROM {first_table}")
                count = cursor.fetchone()[0]
                print(f"\nFirst table '{first_table}': {count:,} rows")

                cursor.execute(f"PRAGMA table_info({first_table})")
                columns = cursor.fetchall()
                print(f"  Columns: {[col[1] for col in columns]}")

                if count > 0:
                    cursor.execute(f"SELECT * FROM {first_table} LIMIT 1")
                    sample = cursor.fetchone()
                    print(f"  Sample row: {sample[:3]}..." if len(sample) > 3 else f"  Sample row: {sample}")

            conn.close()
            return True
        except Exception as e:
            print(f"✗ Error opening as SQLite: {e}")
            return False
    else:
        # Try to open as .mdb (MS Access)
        print(f"✗ Not SQLite. Header: {header[:8].hex()}")
        print("  (Might be MS Access .mdb or proprietary binary format)")

        # Try MDB with pyodbc if available
        try:
            import pyodbc
            print("  → Trying with pyodbc...")
            conn_str = f'Driver={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={fpath};'
            conn = pyodbc.connect(conn_str)
            cursor = conn.cursor()

            # Get table names
            cursor.execute("SELECT Name FROM MSysObjects WHERE Type=1 AND Name NOT LIKE 'MSys%' AND Name NOT LIKE '~%'")
            tables = [row[0] for row in cursor.fetchall()]
            print(f"✓ Opened as Access DB! Tables ({len(tables)}):")
            for table in tables[:5]:
                print(f"  - {table}")
            if len(tables) > 5:
                print(f"  ... and {len(tables)-5} more")
            conn.close()
            return True
        except ImportError:
            print("  → pyodbc not installed (try: pip install pyodbc)")
            return False
        except Exception as e:
            print(f"  → pyodbc error: {e}")
            return False

def main():
    base_path = Path("D:\\projects\\kairos-studio-v2\\_bible_raw")

    # Test all copied files
    test_files = list(base_path.glob("**/*.bdb")) + list(base_path.glob("**/*.sdb")) + list(base_path.glob("**/*.mdb")) + list(base_path.glob("**/*.db"))

    if not test_files:
        print("No test files found in _bible_raw/")
        return 1

    success_count = 0
    for fpath in sorted(test_files):
        if test_sqlite_file(fpath):
            success_count += 1

    print(f"\n{'='*60}")
    print(f"Summary: {success_count}/{len(test_files)} files readable")
    print('='*60)
    return 0 if success_count > 0 else 1

if __name__ == "__main__":
    sys.exit(main())
