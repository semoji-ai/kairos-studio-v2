"""bible_documents.db에 관주 링크·장절 매핑을 구워 넣는다. **빌드 타임 도구.**

bible_documents.db는 tauri.release.conf.json이 `"../bible_documents.db"`로
앱 번들에 굽는 **공통 읽기 전용 자산**이다 — 모든 목사님이 동일한 사본을 받고,
설치된 번들(.app / Program Files)은 쓸 수 없다. 그러니 이 스크립트는 릴리스를
만드는 개발 머신에서 돌린다. build-resources.sh / .ps1이 자동으로 호출하므로
보통은 직접 부를 일이 없고, 기존 DB에 인덱스만 새로 얹을 때 수동으로 쓴다.

목사님별 학습 데이터(대화·피드백·injected_refs)는 여기가 아니라
data_dir/kairos.db(기본 ~/.kairos-studio)에 있다. 이 DB에는 들어가지 않는다.

재인제스트는 하지 않는다 — verse_links / verse_refs만 다시 만든다
(94k 문서 재색인은 수십 분이지만 이건 관주 레코드만 훑어 수 초).

    python3 scripts/build_verse_links.py
    KAIROS_BIBLE_DB=/path/to/bible_documents.db python3 scripts/build_verse_links.py

DB 경로는 KAIROS_BIBLE_DB 환경변수 > 리포지토리 루트의 bible_documents.db 순.

해석 실패한 관주 앵커 표기를 함께 출력한다. 관주 원본의 앵커 필드(jj) 표기가
예상과 다르면 unresolved_anchors가 크게 잡히므로, 그 샘플을 보고
core/documents.py의 ref_key()를 한 번 손보면 된다.
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
