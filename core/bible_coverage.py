"""성경 설교 커버리지 — 위키 설교 기사의 passage를 절 단위로 집계한다.

66권/장별 절 수는 워크스페이스 bible_data의 개역개정 jsonl에서 1회 로드해
캐시하고, 커버리지는 wiki/sermons/*/index.md 프론트매터(passage·title·date)를
스캔해 계산한다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

BOOKS = [
    "창세기", "출애굽기", "레위기", "민수기", "신명기", "여호수아", "사사기", "룻기",
    "사무엘상", "사무엘하", "열왕기상", "열왕기하", "역대상", "역대하", "에스라",
    "느헤미야", "에스더", "욥기", "시편", "잠언", "전도서", "아가", "이사야",
    "예레미야", "예레미야애가", "에스겔", "다니엘", "호세아", "요엘", "아모스",
    "오바댜", "요나", "미가", "나훔", "하박국", "스바냐", "학개", "스가랴", "말라기",
    "마태복음", "마가복음", "누가복음", "요한복음", "사도행전", "로마서",
    "고린도전서", "고린도후서", "갈라디아서", "에베소서", "빌립보서", "골로새서",
    "데살로니가전서", "데살로니가후서", "디모데전서", "디모데후서", "디도서",
    "빌레몬서", "히브리서", "야고보서", "베드로전서", "베드로후서", "요한일서",
    "요한이서", "요한삼서", "유다서", "요한계시록",
]
_ALIAS = {"애가": "예레미야애가", "계시록": "요한계시록", "살전": "데살로니가전서",
          "살후": "데살로니가후서", "고전": "고린도전서", "고후": "고린도후서",
          "딤전": "디모데전서", "딤후": "디모데후서", "벧전": "베드로전서",
          "벧후": "베드로후서", "요일": "요한일서", "요이": "요한이서",
          "요삼": "요한삼서", "왕상": "열왕기상", "왕하": "열왕기하",
          "삼상": "사무엘상", "삼하": "사무엘하", "대상": "역대상", "대하": "역대하",
          "열한계시록": "요한계시록",
          # 흔한 단일/축약 약어 (codex·목사님 원고가 쓰는 표기)
          "창": "창세기", "출": "출애굽기", "레": "레위기", "민": "민수기",
          "신": "신명기", "수": "여호수아", "삿": "사사기", "룻": "룻기",
          "스": "에스라", "느": "느헤미야", "에": "에스더", "욥": "욥기",
          "시": "시편", "잠": "잠언", "전": "전도서", "아": "아가",
          "사": "이사야", "렘": "예레미야", "겔": "에스겔", "단": "다니엘",
          "호": "호세아", "욜": "요엘", "암": "아모스", "옵": "오바댜",
          "욘": "요나", "미": "미가", "나": "나훔", "합": "하박국",
          "습": "스바냐", "학": "학개", "슥": "스가랴", "말": "말라기",
          "마": "마태복음", "막": "마가복음", "눅": "누가복음", "요": "요한복음",
          "행": "사도행전", "롬": "로마서", "갈": "갈라디아서", "엡": "에베소서",
          "빌": "빌립보서", "골": "골로새서", "딛": "디도서", "몬": "빌레몬서",
          "히": "히브리서", "약": "야고보서", "유": "유다서", "계": "요한계시록"}

_verse_counts_cache: dict[str, dict] = {}
_verse_text_cache: dict[str, dict] = {}


def book_num(name: str) -> int | None:
    name = _ALIAS.get(name, name)
    if name in BOOKS:
        return BOOKS.index(name) + 1
    for i, b in enumerate(BOOKS):
        if name and b.startswith(name):
            return i + 1
    return None


def load_verse_counts(workspace_dir: Path) -> dict[int, dict[int, int]]:
    """{book_num: {chapter: 절 수}} — 개역개정 jsonl에서 1회 계산 후 캐시."""
    key = str(workspace_dir)
    if key in _verse_counts_cache:
        return _verse_counts_cache[key]
    counts: dict[int, dict[int, int]] = {}
    jsonl = Path(workspace_dir) / "bible_data" / "bible_text" / "개역개정.jsonl"
    if jsonl.is_file():
        with open(jsonl, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                b, c, v = r.get("book"), r.get("chapter"), r.get("verse")
                if not (isinstance(b, int) and isinstance(c, int) and isinstance(v, int)):
                    continue
                ch = counts.setdefault(b, {})
                if v > ch.get(c, 0):
                    ch[c] = v
    _verse_counts_cache[key] = counts
    return counts


def load_verse_texts(workspace_dir: Path) -> dict[tuple[int, int, int], str]:
    """{(book, chapter, verse): 개역개정 본문} — 1회 로드 후 캐시 (~10MB)."""
    key = str(workspace_dir)
    if key in _verse_text_cache:
        return _verse_text_cache[key]
    texts: dict[tuple[int, int, int], str] = {}
    jsonl = Path(workspace_dir) / "bible_data" / "bible_text" / "개역개정.jsonl"
    if jsonl.is_file():
        with open(jsonl, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                    texts[(r["book"], r["chapter"], r["verse"])] = r["text"].strip()
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue
    _verse_text_cache[key] = texts
    return texts


def verses_block(workspace_dir: str | Path, text: str, max_verses: int = 40) -> str:
    """사용자 입력에서 성경 참조를 파싱해 개역개정 원문 블록을 만든다.

    LLM 기억이 아니라 로컬 베들레헴 DB에서 기계적으로 조회한다. 참조가 없거나
    데이터가 없으면 빈 문자열.
    """
    refs = parse_passage(text)
    if not refs:
        return ""
    texts = load_verse_texts(Path(workspace_dir).expanduser())
    if not texts:
        return ""
    lines, n = [], 0
    for bn, ch, v1, v2 in refs:
        for v in range(v1, v2 + 1):
            t = texts.get((bn, ch, v))
            if t is None:
                continue
            lines.append(f"{BOOKS[bn-1]} {ch}:{v} {t}")
            n += 1
            if n >= max_verses:
                lines.append(f"... (참조 구절이 많아 {max_verses}절까지만 수록)")
                return "[성경 본문 (개역개정, 로컬 DB 기계 조회)]\n" + "\n".join(lines)
    if not lines:
        return ""
    return "[성경 본문 (개역개정, 로컬 DB 기계 조회)]\n" + "\n".join(lines)


_REF_RE = re.compile(
    r"([가-힣]+[가-힣0-9]*)?\s*(\d+)\s*[:장]\s*(\d+)(?:\s*[-~]\s*(\d+))?\s*절?")


def parse_passage(passage: str) -> list[tuple[int, int, int, int]]:
    """passage 문자열 → [(book_num, chapter, v_start, v_end), ...].

    지원: "다니엘 3:16-18", "출애굽기 11:4-6, 20:17"(책 생략 시 직전 책),
    "누가복음 13장 6-9절", "잠언 16:27-29, 요한일서 4:1".
    """
    refs = []
    cur_book = None
    for m in _REF_RE.finditer(passage or ""):
        name, ch, v1, v2 = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)
        if name:
            bn = book_num(name)
            if bn is None:
                continue  # 책 이름이 아닌 한글 어절 (예: 설교 제목 일부)
            cur_book = bn
        if cur_book is None:
            continue
        refs.append((cur_book, ch, v1, int(v2) if v2 else v1))
    return refs


def _read_fm(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    if not m:
        return {}
    fm = {}
    for ln in m.group(1).splitlines():
        mm = re.match(r"^(\w[\w_]*):\s*(.*)$", ln)
        if mm:
            fm[mm.group(1)] = mm.group(2).strip().strip('"')
    return fm


def coverage(workspace_dir: str | Path) -> dict:
    """전체 커버리지 응답 구조를 만든다 (server /bible/coverage)."""
    ws = Path(workspace_dir).expanduser()
    counts = load_verse_counts(ws)
    # 장별 설교 수집: (book, chapter) -> {"ranges": [...], "sermons": [...]}
    per_ch: dict[tuple[int, int], dict] = {}
    sermons_dir = ws / "wiki" / "sermons"
    if sermons_dir.is_dir():
        for d in sorted(p for p in sermons_dir.iterdir() if p.is_dir()):
            fm = _read_fm(d / "index.md")
            passage = fm.get("passage", "")
            if not passage:
                continue
            info = {"title": fm.get("title", d.name), "date": fm.get("date", ""),
                    "article": d.name, "passage": passage}
            for bn, ch, v1, v2 in parse_passage(passage):
                slot = per_ch.setdefault((bn, ch), {"ranges": [], "sermons": []})
                slot["ranges"].append([v1, v2])
                if info not in slot["sermons"]:
                    slot["sermons"].append(info)

    books = []
    for bn, name in enumerate(BOOKS, start=1):
        chapters = []
        ch_count = counts.get(bn, {})
        n_chapters = max(ch_count) if ch_count else 0
        for ch in range(1, n_chapters + 1):
            slot = per_ch.get((bn, ch))
            chapters.append({
                "n": ch,
                "verses": ch_count.get(ch, 0),
                "ranges": slot["ranges"] if slot else [],
                "sermons": slot["sermons"] if slot else [],
            })
        covered = sum(1 for c in chapters if c["ranges"])
        books.append({"num": bn, "name": name, "chapters": chapters,
                      "covered_chapters": covered, "total_chapters": n_chapters})
    return {"books": books}
