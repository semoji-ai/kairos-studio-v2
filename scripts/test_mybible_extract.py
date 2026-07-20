#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test MyBible .mdb file access and extraction."""

import pypyodbc
from pathlib import Path
import json
import sys

# UTF-8 인코딩 강제
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

mybible_path = r"C:\Users\user\Documents\0.성경프로그램-지우지마세요\마이바이블52-무설치버전"
db_file = Path(mybible_path) / "bibledb.mdb"

print(f"파일: {db_file}")
print(f"크기: {db_file.stat().st_size / 1e6:.2f} MB\n")

try:
    # pypyodbc로 시도
    conn_str = f'Driver={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_file};'
    conn = pypyodbc.connect(conn_str)
    cursor = conn.cursor()

    print("[OK] pypyodbc 연결 성공!\n")

    # 테이블 목록 가져오기
    cursor.execute("SELECT Name FROM MSysObjects WHERE Type=1 AND Name NOT LIKE 'MSys%'")
    tables = cursor.fetchall()

    print(f"테이블 {len(tables)}개 발견:\n")
    for i, table in enumerate(tables):
        table_name = table[0]

        # 각 테이블의 행 수와 컬럼 확인
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            count = cursor.fetchone()[0]

            cursor.execute(f"PRAGMA table_info({table_name})")
            cursor.execute(f"SELECT * FROM {table_name} LIMIT 0")
            columns = [desc[0] for desc in cursor.description]

            print(f"{i+1}. {table_name}")
            print(f"   행 수: {count:,}, 컬럼: {', '.join(columns[:5])}")

            # bibledb 테이블이면 샘플 출력
            if table_name.lower() == "bibledb":
                cursor.execute(f"SELECT * FROM {table_name} LIMIT 3")
                samples = cursor.fetchall()
                print(f"   샘플 데이터: {samples[0] if samples else '없음'}")

            print()
        except Exception as e:
            print(f"   [INFO FAIL] 정보 조회 실패: {e}\n")

    conn.close()

except Exception as e:
    print(f"[FAIL] {type(e).__name__}: {e}")
    print("\n다른 방법 시도...")
