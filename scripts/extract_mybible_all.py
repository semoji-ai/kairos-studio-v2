# -*- coding: utf-8 -*-
"""마이바이블 모든 데이터 추출 (별도 .mdb 파일들)"""

import pypyodbc
from pathlib import Path
import json
import sys

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

mybible_root = Path(r"C:\Users\user\Documents\0.성경프로그램-지우지마세요\마이바이블52-무설치버전")
output_dir = Path("D:\\projects\\kairos-studio-v2\\bible_data\\mybible")
output_dir.mkdir(parents=True, exist_ok=True)

print(f"MyBible 폴더: {mybible_root}")
print(f"출력 폴더: {output_dir}\n")

# 추출할 데이터 정의
data_sources = [
    ("dicword.mdb", "dicword", "단어 사전/주석", "mybible_dicword"),
    ("dicman.mdb", "dicman", "사전 메타데이터", "mybible_dicman"),
    ("kwanju2.mdb", "kwanju2", "관주/주석 링크", "mybible_kwanju2"),
    ("gongdong.mdb", "bibledb", "공동번역 성경", "mybible_gongdong"),
    ("nivdb.mdb", "bibledb", "NIV 번역", "mybible_nivdb"),
]

total_records = {}

for mdb_file, table_name, desc, output_name in data_sources:
    db_path = mybible_root / mdb_file

    if not db_path.exists():
        print(f"[SKIP] {mdb_file} - 파일 없음")
        continue

    print(f"=== {desc} ({mdb_file}) ===")

    try:
        conn_str = f'Driver={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={str(db_path)};'
        conn = pypyodbc.connect(conn_str)
        cursor = conn.cursor()

        # 테이블 확인
        try:
            cursor.execute(f"SELECT COUNT(*) FROM [{table_name}]")
            count = cursor.fetchone()[0]
            print(f"총 {count:,}개 항목")

            # 컬럼 정보
            cursor.execute(f"SELECT TOP 1 * FROM [{table_name}]")
            cols = [desc[0] for desc in cursor.description]
            print(f"컬럼 ({len(cols)}): {', '.join(cols[:6])}{'...' if len(cols) > 6 else ''}\n")

            # 데이터 추출
            print("추출 중...")
            cursor.execute(f"SELECT * FROM [{table_name}]")

            output_file = output_dir / f"{output_name}.jsonl"
            record_count = 0

            with open(output_file, 'w', encoding='utf-8') as f:
                for row in cursor.fetchall():
                    record = {cols[j]: row[j] for j in range(len(cols))}
                    record['source'] = output_name
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                    record_count += 1

                    if record_count % 5000 == 0:
                        print(f"  {record_count:,}개 처리...")

            print(f"[완료] {output_file}")
            print(f"저장됨: {record_count:,}개\n")
            total_records[output_name] = record_count

        except Exception as e:
            print(f"[FAIL] 테이블 '{table_name}' 접근 실패: {str(e)[:80]}\n")

        conn.close()

    except Exception as e:
        print(f"[FAIL] {mdb_file} 연결 실패: {str(e)[:80]}\n")

print("=" * 60)
print("[OK] MyBible 전체 추출 완료!")
print("\n=== 추출 결과 ===")
for name, count in total_records.items():
    print(f"  {name}: {count:,}")
print(f"  합계: {sum(total_records.values()):,}개")
