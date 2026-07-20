# -*- coding: utf-8 -*-
"""Bethlehem .dct 파일 포맷 분석"""

from pathlib import Path
import struct
import sys

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

dct_file = Path(r"C:\Users\user\Documents\0.성경프로그램-지우지마세요\PC용베들레헴성경-개신교용\HebGrkKo.dct")

print(f"파일: {dct_file.name}")
print(f"크기: {dct_file.stat().st_size / 1e6:.2f} MB\n")

# 파일 헤더 분석
print("=== 파일 헤더 분석 ===")
with open(dct_file, 'rb') as f:
    # 처음 512바이트 읽기
    header = f.read(512)

    # 1. 매직 넘버/시그니처 확인
    print(f"처음 16바이트 (hex): {header[:16].hex()}")
    print(f"처음 16바이트 (ascii): {header[:16]}")

    # 2. 파일 크기
    file_size = dct_file.stat().st_size
    print(f"\n파일 크기: {file_size:,} bytes")

    # 3. 반복 패턴 찾기 (주로 null bytes가 많으면 구조가 있을 가능성)
    null_count = header.count(b'\x00')
    print(f"헤더의 null bytes: {null_count}/{len(header)}")

    # 4. 텍스트 문자열 찾기
    print("\n=== 텍스트 문자열 (처음 1KB) ===")
    try:
        text = header.decode('utf-8', errors='ignore')
        # 인쇄 가능한 ASCII 또는 한글만 추출
        printable = ''.join(c for c in text if ord(c) >= 32 or c == '\n')
        if printable:
            print(printable[:200])
    except:
        pass

    # 5. 구조 힌트 찾기 (크기 정보, 오프셋 등)
    print("\n=== 구조 분석 ===")
    try:
        # 작은 정수값들을 찾아보기
        for i in range(0, min(100, len(header) - 4), 4):
            val = struct.unpack('<I', header[i:i+4])[0]
            if 100 < val < 100000:  # 합리적인 크기
                print(f"Offset {i}: {val:,} (0x{val:x})")
    except:
        pass

    # 6. 끝부분도 확인
    print("\n=== 파일 끝부분 분석 ===")
    f.seek(-512, 2)
    tail = f.read(512)
    print(f"끝 16바이트 (hex): {tail[-16:].hex()}")

print("\n=== 결론 ===")
print("포맷이 불명확함. 다음 방법 시도 필요:")
print("1. Bethlehem 프로그램의 ini/config 파일 확인")
print("2. 프로그램의 언로드된 DLL에서 파일 포맷 역공학")
print("3. 온라인 Bethlehem 포럼/문서 검색")
print("4. 대안: Bethlehem 프로그램 자체의 내보내기 기능 사용")
