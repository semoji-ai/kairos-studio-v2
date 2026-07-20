# -*- coding: utf-8 -*-
"""마이바이블 복사본에서 테이블 접근 시도"""

import pypyodbc
from pathlib import Path

db_file = r"D:\projects\kairos-studio-v2\_bible_raw\mybible_bibledb.mdb"

print(f"파일: {Path(db_file).name}")
print(f"크기: {Path(db_file).stat().st_size / 1e6:.2f} MB\n")

try:
    conn_str = f'Driver={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_file};'
    conn = pypyodbc.connect(conn_str)
    cursor = conn.cursor()

    print("[OK] 연결 성공!\n")

    # 쿼리 실행 - 다양한 방식 시도
    queries = [
        "SELECT * FROM bibledb LIMIT 1",
        "SELECT TOP 1 * FROM bibledb",
        "SELECT * FROM [bibledb] LIMIT 1",
        "SELECT * FROM `bibledb` LIMIT 1",
    ]

    for i, query in enumerate(queries, 1):
        try:
            cursor.execute(query)
            cols = [desc[0] for desc in cursor.description]
            print(f"[{i}] 성공! 쿼리: {query}")
            print(f"    컬럼: {cols}\n")
            break
        except Exception as e:
            print(f"[{i}] 실패: {query}")
            print(f"    오류: {str(e)[:80]}\n")

    conn.close()

except Exception as e:
    print(f"[FAIL] {type(e).__name__}: {e}")
