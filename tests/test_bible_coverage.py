# -*- coding: utf-8 -*-
import json

from core import bible_coverage


def test_parse_passage_basic():
    assert bible_coverage.parse_passage("다니엘 3:16-18") == [(27, 3, 16, 18)]


def test_parse_passage_multi_and_book_carry():
    # 책 생략 시 직전 책 유지: "출애굽기 11:4-6, 20:17"
    refs = bible_coverage.parse_passage("출애굽기 11:4-6, 20:17")
    assert refs == [(2, 11, 4, 6), (2, 20, 17, 17)]


def test_parse_passage_two_books():
    refs = bible_coverage.parse_passage("잠언 16:27-29, 요한일서 4:1")
    assert refs == [(20, 16, 27, 29), (62, 4, 1, 1)]


def test_parse_passage_jang_jeol_format():
    assert bible_coverage.parse_passage("누가복음 13장 6-9절") == [(42, 13, 6, 9)]


def test_parse_passage_garbage_returns_empty():
    assert bible_coverage.parse_passage("") == []
    assert bible_coverage.parse_passage("설교 제목일 뿐") == []


def test_coverage_from_workspace(tmp_path):
    # 최소 워크스페이스: 개역개정 jsonl(창세기 1장 3절까지) + 설교 기사 1건
    bt = tmp_path / "bible_data" / "bible_text"
    bt.mkdir(parents=True)
    rows = [{"book": 1, "chapter": 1, "verse": v, "text": "t"} for v in (1, 2, 3)]
    (bt / "개역개정.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    art = tmp_path / "wiki" / "sermons" / "2026-01-01_테스트"
    art.mkdir(parents=True)
    (art / "index.md").write_text(
        '---\ntitle: "테스트 설교"\ndate: 2026-01-01\npassage: "창세기 1:1-2"\n---\n본문',
        encoding="utf-8")

    cov = bible_coverage.coverage(tmp_path)
    gen = cov["books"][0]
    assert gen["name"] == "창세기"
    assert gen["total_chapters"] == 1
    assert gen["covered_chapters"] == 1
    ch1 = gen["chapters"][0]
    assert ch1["verses"] == 3
    assert ch1["ranges"] == [[1, 2]]
    assert ch1["sermons"][0]["title"] == "테스트 설교"
    # 미커버 책은 장 정보 없음(카운트 데이터에 없으므로 0장)
    assert cov["books"][1]["total_chapters"] == 0


def test_verses_block_mechanical_lookup(tmp_path):
    import json as _json
    bt = tmp_path / "bible_data" / "bible_text"
    bt.mkdir(parents=True)
    rows = [{"book": 45, "chapter": 8, "verse": v, "text": f"로마서 본문 {v}"}
            for v in (1, 2, 3, 4, 5)]
    (bt / "개역개정.jsonl").write_text(
        "\n".join(_json.dumps(r) for r in rows), encoding="utf-8")

    blk = bible_coverage.verses_block(tmp_path, "로마서 8:1-3으로 설교 준비해줘")
    assert "[성경 본문" in blk
    assert "로마서 8:1 로마서 본문 1" in blk
    assert "로마서 8:3 로마서 본문 3" in blk
    assert "8:4" not in blk  # 요청 범위 밖은 미포함
    assert bible_coverage.verses_block(tmp_path, "안녕하세요") == ""
