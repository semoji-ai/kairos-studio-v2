"""기존 bible_documents.db에서 관주 링크·장절 매핑을 재구축한다.

재인제스트 없이 verse_links / verse_refs 만 다시 만든다 (94k 문서 재색인은
수십 분 걸리지만 이 스크립트는 관주 레코드만 훑는다).

    python3 scripts/build_verse_links.py
    KAIROS_BIBLE_DB=/path/to/bible_documents.db python3 scripts/build_verse_links.py

DB 경로는 KAIROS_BIBLE_DB 환경변수 > 리포지토리 루트의 bible_documents.db 순.

해석 실패한 관주 앵커 표기를 함께 출력한다. 관주 원본의 앵커 필드(jj) 표기가
예상과 다르면 unresolved_anchors 가 크게 잡히므로, 그 샘플을 보고
core/documents.py 의 ref_key() 를 한 번 손보면 된다.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import documents  # noqa: E402


def main() -> int:
    db_path = Path(
        os.environ.get("KAIROS_BIBLE_DB")
        or Path(__file__).resolve().parent.parent / "bible_documents.db"
    )
    if not db_path.is_file():
        print(f"[error] DB를 찾을 수 없습니다: {db_path}")
        print("        KAIROS_BIBLE_DB 로 경로를 지정하세요.")
        return 1

    print(f"[*] {db_path}")
    stats = documents.rebuild_verse_index(db_path)

    print(f"    장절 매핑(verse_refs):     {stats['verse_refs']:,}")
    print(f"    관주 링크(verse_links):    {stats['verse_links']:,}")
    print(f"    링크를 가진 앵커 구절:      {stats['linked_anchors']:,}")
    print(f"    앵커 해석 실패:            {stats['unresolved_anchors']:,}")
    print(f"    앵커는 풀렸으나 링크 0건:   {stats['unlinked_anchors']:,}")

    samples = stats["unresolved_anchor_samples"]
    if samples:
        print("\n[!] 해석하지 못한 앵커 표기 샘플:")
        for sample in samples:
            print(f"      {sample!r}")
        print("    → core/documents.py 의 ref_key() 에 이 형식을 추가하세요.")

    if stats["verse_links"] == 0:
        print("\n[!] 링크가 하나도 만들어지지 않았습니다.")
        print("    관주(cross_reference) 레코드가 색인돼 있는지 확인하세요:")
        print("      SELECT COUNT(*) FROM documents WHERE type='cross_reference';")
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
