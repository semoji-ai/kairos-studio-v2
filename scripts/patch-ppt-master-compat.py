"""Apply Kairos compatibility fixes to a staged, pinned PPT Master copy."""
from __future__ import annotations

import sys
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    if old not in source:
        raise RuntimeError(f"PPT Master compatibility anchor missing: {label}")
    return source.replace(old, new, 1)


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch-ppt-master-compat.py PPT_MASTER_ROOT")
    root = Path(sys.argv[1])
    target = (
        root
        / "skills"
        / "ppt-master"
        / "scripts"
        / "svg_to_pptx"
        / "drawingml"
        / "utils.py"
    )
    source = target.read_text(encoding="utf-8")
    source = replace_once(
        source,
        """    return (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or
            0x2E80 <= cp <= 0x2EFF or 0x3000 <= cp <= 0x303F or""",
        """    return (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or
            0x3040 <= cp <= 0x30FF or 0x31F0 <= cp <= 0x31FF or
            0x1100 <= cp <= 0x11FF or 0x3130 <= cp <= 0x318F or
            0xA960 <= cp <= 0xA97F or 0xAC00 <= cp <= 0xD7AF or
            0xD7B0 <= cp <= 0xD7FF or
            0x2E80 <= cp <= 0x2EFF or 0x3000 <= cp <= 0x303F or""",
        "Hangul/Japanese width ranges",
    )
    source = replace_once(
        source,
        """def detect_text_lang(text: str) -> str:
    \"\"\"Return a DrawingML language tag for a text run.\"\"\"
    return 'zh-CN' if any(is_cjk_char(ch) for ch in text) else 'en-US'""",
        """def detect_text_lang(text: str) -> str:
    \"\"\"Return a DrawingML language tag for a text run.\"\"\"
    if any(0x1100 <= ord(ch) <= 0x11FF or
           0x3130 <= ord(ch) <= 0x318F or
           0xA960 <= ord(ch) <= 0xA97F or
           0xAC00 <= ord(ch) <= 0xD7AF or
           0xD7B0 <= ord(ch) <= 0xD7FF for ch in text):
        return 'ko-KR'
    if any(0x3040 <= ord(ch) <= 0x30FF or
           0x31F0 <= ord(ch) <= 0x31FF for ch in text):
        return 'ja-JP'
    return 'zh-CN' if any(is_cjk_char(ch) for ch in text) else 'en-US'""",
        "East Asian language tags",
    )
    source = replace_once(
        source,
        """    if detect_text_lang(text) == 'zh-CN':
        ea = fonts['ea']""",
        """    if detect_text_lang(text) != 'en-US':
        ea = fonts['ea']""",
        "East Asian font routing",
    )
    target.write_text(source, encoding="utf-8")

    elements = target.with_name("elements.py")
    source = elements.read_text(encoding="utf-8")
    source = replace_once(
        source,
        """                boundary_is_cjk = (
                    (prev_text and is_cjk_char(prev_text[-1]))
                    or (next_text and is_cjk_char(next_text[0]))
                )""",
        """                boundary_is_cjk = (
                    (prev_text and is_cjk_char(prev_text[-1]))
                    or (next_text and is_cjk_char(next_text[0]))
                ) and not (
                    (prev_text and detect_text_lang(prev_text[-1]) == 'ko-KR')
                    or (next_text and detect_text_lang(next_text[0]) == 'ko-KR')
                )""",
        "Korean soft-wrap spaces",
    )
    elements.write_text(source, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
