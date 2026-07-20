# -*- coding: utf-8 -*-
"""마이바이블 .mdb 파일에서 성경 본문 직접 추출"""

import pypyodbc
from pathlib import Path
import json
import sys

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

mybible_path = r"C:\Users\user\Documents\0.성경프로그램-지우지마세요\마이바이블52-무설치버전"
db_file = Path(mybible_path) / "bibledb.mdb"

print(f"파일: {db_file.name}")
print(f"크기: {db_file.stat().st_size / 1e6:.2f} MB\n")

try:
    # ODBC 연결
    conn_str = f'Driver={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_file};'
    conn = pypyodbc.connect(conn_str)
    cursor = conn.cursor()

    print("[OK] 연결 성공!\n")

    # 1. bibledb 테이블 구조 확인
    print("=== bibledb 테이블 분석 ===")
    try:
        cursor.execute("SELECT * FROM bibledb LIMIT 1")
        columns = [desc[0] for desc in cursor.description]
        print(f"컬럼: {columns}\n")

        # 전체 행 수
        cursor.execute("SELECT COUNT(*) FROM bibledb")
        count = cursor.fetchone()[0]
        print(f"총 {count:,}개 행\n")

        # 샘플 데이터
        print("샘플 데이터 (처음 3개):")
        cursor.execute("SELECT * FROM bibledb LIMIT 3")
        for i, row in enumerate(cursor.fetchall(), 1):
            print(f"  {i}. {row}")

    except Exception as e:
        print(f"[FAIL] bibledb 접근 실패: {e}\n")

    # 2. 다른 테이블들도 시도
    print("\n=== 다른 테이블 시도 ===")
    tables_to_try = [
        "dicman",      # 사전
        "dicword",     # 단어 사전
        "kwanju2",     # 관주
        "nivdb",       # NIV 번역
        "gongdong"     # 공동번역
    ]

    for table_name in tables_to_try:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM [{table_name}]")
            count = cursor.fetchone()[0]

            cursor.execute(f"SELECT * FROM [{table_name}] LIMIT 0")
            columns = [desc[0] for desc in cursor.description]

            print(f"{table_name}: {count:,}개 행, 컬럼 {len(columns)}개")

        except Exception as e:
            print(f"{table_name}: 접근 불가 ({str(e)[:50]}...)")

    conn.close()
    print("\n[완료]")

except Exception as e:
    print(f"[연결 실패] {type(e).__name__}: {e}")
