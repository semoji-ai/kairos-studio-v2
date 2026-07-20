# -*- coding: utf-8 -*-
"""마이바이블 데이터 전체 추출"""

import pypyodbc
from pathlib import Path
import json
import sys

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

db_file = r"D:\projects\kairos-studio-v2\_bible_raw\mybible_bibledb.mdb"
output_dir = Path("D:\\projects\\kairos-studio-v2\\bible_data\\mybible")
output_dir.mkdir(parents=True, exist_ok=True)

print(f"원본 파일: {Path(db_file).name}")
print(f"출력 폴더: {output_dir}\n")

try:
    conn_str = f'Driver={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_file};'
    conn = pypyodbc.connect(conn_str)
    cursor = conn.cursor()

    print("[OK] 연결 성공!\n")

    # 1. bibledb 테이블 분석
    print("=== bibledb 데이터 추출 ===")
    cursor.execute("SELECT COUNT(*) FROM bibledb")
    count = cursor.fetchone()[0]
    print(f"총 {count:,}개 행\n")

    # 2. 데이터 추출
    print("데이터 추출 중...")
    cursor.execute("SELECT code, pchp, tchp, book, content FROM bibledb ORDER BY code")

    output_file = output_dir / "mybible_bibledb.jsonl"
    with open(output_file, 'w', encoding='utf-8') as f:
        for i, row in enumerate(cursor.fetchall(), 1):
            code, pchp, tchp, book, content = row

            record = {
                "id": code,
                "book": book,
                "reference": tchp,  # 현재 장:절
                "content": content,
                "source": "mybible"
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

            if i % 5000 == 0:
                print(f"  {i:,}개 처리...")

    print(f"\n[완료] {output_file}")
    print(f"저장됨: {i:,}개 행")

    # 3. 다른 테이블들도 시도
    print("\n=== 다른 테이블 확인 ===")
    other_tables = ["dicman", "dicword", "kwanju2", "nivdb", "gongdong"]

    for table_name in other_tables:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM [{table_name}]")
            count = cursor.fetchone()[0]

            cursor.execute(f"SELECT TOP 1 * FROM [{table_name}]")
            cols = [desc[0] for desc in cursor.description]

            print(f"{table_name}: {count:,}개 행, 컬럼: {cols}")

        except Exception as e:
            pass

    conn.close()

except Exception as e:
    print(f"[FAIL] {type(e).__name__}: {e}")
