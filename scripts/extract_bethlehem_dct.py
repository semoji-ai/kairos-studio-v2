# -*- coding: utf-8 -*-
"""베들레헴 .dct SQLite 파일 추출 (한글 사전/주석)"""

import sqlite3
from pathlib import Path
import json
import sys

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

dct_files = [
    (Path(r"C:\Users\user\Documents\0.성경프로그램-지우지마세요\PC용베들레헴성경-개신교용\HebGrkKo.dct"), "HebGrkKo", "한글"),
    (Path(r"C:\Users\user\Documents\0.성경프로그램-지우지마세요\PC용베들레헴성경-개신교용\HebGrkEn.dct"), "HebGrkEn", "영문"),
]

output_dir = Path("D:\\projects\\kairos-studio-v2\\bible_data\\bethlehem_commentary")
output_dir.mkdir(parents=True, exist_ok=True)

print(f"출력 폴더: {output_dir}\n")

total_records = {}

for dct_path, dct_name, lang in dct_files:
    if not dct_path.exists():
        print(f"[SKIP] {dct_name} - 파일 없음")
        continue

    print(f"=== {lang} 사전 ({dct_name}.dct) ===")
    print(f"파일 크기: {dct_path.stat().st_size / 1e6:.2f} MB")

    try:
        conn = sqlite3.connect(str(dct_path))
        cursor = conn.cursor()

        # 테이블 목록 확인
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        print(f"테이블 {len(tables)}개: {', '.join(tables[:5])}{'...' if len(tables) > 5 else ''}\n")

        # 각 테이블 분석 및 추출
        for table_name in tables:
            if table_name.startswith('sqlite_'):
                continue  # 시스템 테이블 제외

            try:
                # 행 수 확인
                cursor.execute(f"SELECT COUNT(*) FROM [{table_name}]")
                count = cursor.fetchone()[0]

                if count == 0:
                    continue

                # 컬럼 정보
                cursor.execute(f"PRAGMA table_info([{table_name}])")
                columns = [row[1] for row in cursor.fetchall()]

                print(f"  [{table_name}]")
                print(f"    행 수: {count:,}")
                print(f"    컬럼: {', '.join(columns[:5])}{'...' if len(columns) > 5 else ''}")

                # 데이터 추출
                cursor.execute(f"SELECT * FROM [{table_name}]")
                output_file = output_dir / f"bethel_{dct_name}_{table_name}.jsonl"

                record_count = 0
                with open(output_file, 'w', encoding='utf-8') as f:
                    for row in cursor.fetchall():
                        record = {columns[i]: row[i] for i in range(len(columns))}
                        record['source'] = f'bethel_{dct_name}'
                        record['table'] = table_name
                        f.write(json.dumps(record, ensure_ascii=False) + "\n")
                        record_count += 1

                        if record_count % 10000 == 0:
                            print(f"      ... {record_count:,}개 처리")

                print(f"    [완료] {output_file.name}: {record_count:,}개\n")
                key = f"{dct_name}_{table_name}"
                total_records[key] = record_count

            except Exception as e:
                print(f"    [FAIL] {table_name}: {str(e)[:60]}\n")

        conn.close()

    except Exception as e:
        print(f"[FAIL] {dct_name} 파일 열기 실패: {e}\n")

print("=" * 60)
print("[OK] Bethlehem 사전 추출 완료!")
print("\n=== 추출 결과 ===")
for name, count in sorted(total_records.items()):
    print(f"  {name}: {count:,}")
print(f"  합계: {sum(total_records.values()):,}개")
