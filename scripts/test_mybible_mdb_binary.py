# -*- coding: utf-8 -*-
"""MDB 파일 바이너리 분석 및 구조 파악"""

from pathlib import Path
import struct

mybible_path = r"C:\Users\user\Documents\0.성경프로그램-지우지마세요\마이바이블52-무설치버전"
db_file = Path(mybible_path) / "bibledb.mdb"

print("[바이너리 분석]")
print(f"파일: {db_file.name}")
print(f"크기: {db_file.stat().st_size / 1e6:.2f} MB\n")

# 파일 헤더 읽기
with open(db_file, 'rb') as f:
    # 처음 20바이트 확인 (MDB 서명)
    header = f.read(20)
    print(f"파일 서명: {header[:8]}")  # 보통 "Standard" (MS Access)

    # 전체 크기
    f.seek(0, 2)
    file_size = f.tell()
    print(f"전체 크기: {file_size:,} bytes")

    # 페이지 크기 확인 (offset 22-23)
    f.seek(22)
    page_size = struct.unpack('<H', f.read(2))[0]
    print(f"페이지 크기: {page_size} bytes")

    print("\n[접근 가능한 대안]")
    print("1. MS Excel VBA 매크로 (Windows 전용)")
    print("2. 마이바이블 프로그램의 내보내기 기능")
    print("3. Wine/WSL을 통한 Linux MDB 도구")
    print("4. LibreOffice Base (GUI)")
    print("5. ODBC 드라이버 권한 설정 재조정")
