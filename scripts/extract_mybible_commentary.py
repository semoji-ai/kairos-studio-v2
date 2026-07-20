# -*- coding: utf-8 -*-
"""마이바이블 주석/사전/관주 데이터 추출"""

import pypyodbc
from pathlib import Path
import json
import sys

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

db_file = r"C:\Users\user\Documents\0.성경프로그램-지우지마세요\마이바이블52-무설치버전\bibledb.mdb"
output_dir = Path("D:\\projects\\kairos-studio-v2\\bible_data\\mybible")
output_dir.mkdir(parents=True, exist_ok=True)

print(f"원본 파일: {Path(db_file).name}")
print(f"출력 폴더: {output_dir}\n")

try:
    conn_str = f'Driver={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_file};'
    conn = pypyodbc.connect(conn_str)
    cursor = conn.cursor()

    print("[OK] 연결 성공!\n")

    # 1. dicword 테이블 (단어 사전/주석)
    print("=== dicword 테이블 분석 (단어 사전) ===")
    try:
        cursor.execute("SELECT COUNT(*) FROM dicword")
        count = cursor.fetchone()[0]
        print(f"총 {count:,}개 항목\n")

        cursor.execute("SELECT TOP 1 * FROM dicword")
        cols = [desc[0] for desc in cursor.description]
        print(f"컬럼: {cols}\n")

        # 데이터 추출
        print("데이터 추출 중...")
        cursor.execute("SELECT * FROM dicword ORDER BY id")

        output_file = output_dir / "mybible_dicword.jsonl"
        with open(output_file, 'w', encoding='utf-8') as f:
            for i, row in enumerate(cursor.fetchall(), 1):
                # 동적으로 컬럼 매핑
                record = {cols[j]: row[j] for j in range(len(cols))}
                record['source'] = 'mybible_dicword'
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

                if i % 5000 == 0:
                    print(f"  {i:,}개 처리...")

        print(f"[완료] {output_file}")
        print(f"저장됨: {i:,}개 항목\n")

    except Exception as e:
        print(f"[FAIL] dicword 추출 실패: {e}\n")

    # 2. kwanju2 테이블 (관주/주석 링크)
    print("=== kwanju2 테이블 분석 (관주/주석) ===")
    try:
        cursor.execute("SELECT COUNT(*) FROM kwanju2")
        count = cursor.fetchone()[0]
        print(f"총 {count:,}개 항목\n")

        cursor.execute("SELECT TOP 1 * FROM kwanju2")
        cols = [desc[0] for desc in cursor.description]
        print(f"컬럼: {cols}\n")

        # 데이터 추출
        print("데이터 추출 중...")
        cursor.execute("SELECT * FROM kwanju2 ORDER BY id")

        output_file = output_dir / "mybible_kwanju2.jsonl"
        with open(output_file, 'w', encoding='utf-8') as f:
            for i, row in enumerate(cursor.fetchall(), 1):
                record = {cols[j]: row[j] for j in range(len(cols))}
                record['source'] = 'mybible_kwanju2'
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

                if i % 5000 == 0:
                    print(f"  {i:,}개 처리...")

        print(f"[완료] {output_file}")
        print(f"저장됨: {i:,}개 항목\n")

    except Exception as e:
        print(f"[FAIL] kwanju2 추출 실패: {e}\n")

    # 3. dicman 테이블 (사전 메타데이터)
    print("=== dicman 테이블 분석 (사전 메타) ===")
    try:
        cursor.execute("SELECT COUNT(*) FROM dicman")
        count = cursor.fetchone()[0]
        print(f"총 {count:,}개 항목\n")

        cursor.execute("SELECT TOP 1 * FROM dicman")
        cols = [desc[0] for desc in cursor.description]
        print(f"컬럼: {cols}\n")

        cursor.execute("SELECT * FROM dicman")
        output_file = output_dir / "mybible_dicman.jsonl"
        with open(output_file, 'w', encoding='utf-8') as f:
            for i, row in enumerate(cursor.fetchall(), 1):
                record = {cols[j]: row[j] for j in range(len(cols))}
                record['source'] = 'mybible_dicman'
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        print(f"[완료] {output_file}")
        print(f"저장됨: {i:,}개 항목\n")

    except Exception as e:
        print(f"[FAIL] dicman 추출 실패: {e}\n")

    conn.close()
    print("=" * 60)
    print("[OK] MyBible 주석/사전 추출 완료!")

except Exception as e:
    print(f"[FAIL] {type(e).__name__}: {e}")
