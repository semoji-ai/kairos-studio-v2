# -*- coding: utf-8 -*-
"""성경지도 상세 메타데이터 추가"""

from pathlib import Path
import json
import sys

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

maps_src = Path(r"C:\Users\user\Documents\0.성경프로그램-지우지마세요\성경지도모음_고화질")
maps_dst = Path("D:\\projects\\kairos-studio-v2\\bible_data\\maps")
output_dir = maps_dst
output_dir.mkdir(parents=True, exist_ok=True)

print(f"성경지도 폴더: {maps_src}")
print(f"출력 폴더: {output_dir}\n")

# 파일명에서 주제 추출 및 메타데이터 구성
def parse_map_title(filename):
    """
    파일명으로부터 한글 제목과 주제 추출
    예: "01.성경지도목차1.jpg" -> ("성경지도목차1", ["목차", "개요"])
    """
    name = filename.replace('.jpg', '').split('.')[-1]

    # 주제 태그 자동 추론
    tags = []
    if '목차' in name:
        tags.append('목차')
    if '연대' in name:
        tags.append('연대')
        if '왕' in name:
            tags.append('왕국')
        if '사사' in name:
            tags.append('사사')
        if '대언자' in name or '선지자' in name:
            tags.append('선지자')
    if '지도' in name:
        tags.append('지도')
        if '여행' in name or '선교' in name:
            tags.append('선교여행')
        if '정복' in name:
            tags.append('가나안 정복')
        if '인구' in name or '분포' in name:
            tags.append('부족 분배')
    if '가나안' in name:
        tags.append('가나안')
    if '북' in name or '남' in name:
        tags.append('분열 왕국')
    if '포로' in name or '귀환' in name:
        tags.append('포로기')
    if '신약' in name:
        tags.append('신약')
    if '제자' in name or '사도' in name:
        tags.append('사도행전')
    if '바울' in name:
        tags.append('바울 선교')
    if '로마' in name:
        tags.append('로마 제국')
    if '유대' in name:
        tags.append('유대')
    if '예루살렘' in name or '성전' in name:
        tags.append('예루살렘')

    if not tags:
        tags.append('기타')

    return name, tags

# 지도 파일 스캔
print("=== 성경지도 메타데이터 생성 ===\n")

map_files = sorted(maps_src.glob("*.jpg"))
print(f"발견된 파일: {len(map_files)}개\n")

maps_index = []
record_count = 0

for i, map_file in enumerate(map_files, 1):
    filename = map_file.name
    title, tags = parse_map_title(filename)

    # 파일 크기 확인
    file_size = map_file.stat().st_size

    map_record = {
        "id": i,
        "filename": filename,
        "title": title,
        "tags": tags,
        "path": str(maps_dst / filename),
        "file_size": file_size,
        "source": "bethlehem_maps"
    }

    maps_index.append(map_record)

    # 파일 카피 (아직 안 했으면)
    dst_file = maps_dst / filename
    if not dst_file.exists():
        import shutil
        shutil.copy2(map_file, dst_file)
        print(f"[{i:2d}] {filename[:40]:40} -> {len(tags)} tags")
    else:
        print(f"[{i:2d}] {filename[:40]:40} (이미 존재)")

    record_count += 1

# 메타데이터 JSON 저장
index_file = output_dir / "maps_detailed_index.jsonl"
print(f"\n=== 메타데이터 저장 ===\n")
with open(index_file, 'w', encoding='utf-8') as f:
    for record in maps_index:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

print(f"[완료] {index_file.name}: {len(maps_index)}개\n")

# 태그별 통계
print("=== 태그 통계 ===\n")
all_tags = {}
for record in maps_index:
    for tag in record['tags']:
        all_tags[tag] = all_tags.get(tag, 0) + 1

for tag, count in sorted(all_tags.items(), key=lambda x: -x[1]):
    print(f"  {tag}: {count}개")

print(f"\n[OK] 성경지도 메타데이터 추가 완료!")
print(f"총 {len(maps_index)}개 지도, {len(all_tags)}개 고유 태그")
