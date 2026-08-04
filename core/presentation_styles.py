"""Reusable presentation style presets for Kairos Studio."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


_PRESETS_PATH = Path(__file__).with_name("presentation_style_presets.json")


@lru_cache(maxsize=1)
def _catalog() -> dict:
    payload = json.loads(_PRESETS_PATH.read_text(encoding="utf-8"))
    styles = payload.get("styles")
    if not isinstance(styles, list) or not styles:
        raise RuntimeError("presentation style preset catalog is empty")
    return payload


def list_presentation_styles() -> list[dict]:
    """Return UI-safe style metadata without the full generation brief."""
    return [
        {
            "id": str(style["id"]),
            "name": str(style["name"]),
            "description": str(style.get("description") or ""),
            "tone": str(style.get("tone") or ""),
        }
        for style in _catalog()["styles"]
    ]


def default_presentation_style() -> str:
    return str(_catalog().get("default") or "adaptive")


def list_image_styles() -> list[dict]:
    """Return the image media choices exposed before generation starts."""
    return [
        {
            "id": str(style["id"]),
            "name": str(style["name"]),
            "description": str(style.get("description") or ""),
        }
        for style in _catalog().get("image_styles") or []
    ]


def default_image_style() -> str:
    return str(_catalog().get("default_image_style") or "cinematic-documentary")


def get_image_style(style_id: str | None) -> dict:
    selected = style_id or default_image_style()
    for style in _catalog().get("image_styles") or []:
        if style.get("id") == selected:
            return style
    raise ValueError(f"지원하지 않는 AI 이미지 스타일입니다: {selected}")


def image_style_prompt(style_id: str | None) -> str:
    style = get_image_style(style_id)
    return (
        f"사용자가 선택한 AI 이미지 스타일: {style['name']} (`{style['id']}`)\n"
        "아래 Visual DNA는 작업 전체에서 변경할 수 없는 고정 문자열입니다. "
        "모든 이미지 항목은 같은 image_style_id와 visual_dna를 사용하고, 각 prompt에도 "
        "이 문자열을 그대로 포함하세요. 장면의 피사체와 구도만 달리하고 매체·렌즈·조명·"
        "색보정·질감은 섞거나 변형하지 마세요.\n"
        f"Visual DNA: {style['visual_dna']}"
    )


def get_presentation_style(style_id: str | None) -> dict:
    selected = style_id or default_presentation_style()
    for style in _catalog()["styles"]:
        if style.get("id") == selected:
            return style
    raise ValueError(f"알 수 없는 프레젠테이션 스타일입니다: {selected}")


def presentation_style_prompt(style_id: str | None) -> str:
    style = get_presentation_style(style_id)
    brief = style.get("design_brief")
    if not brief:
        return (
            "스타일 프리셋: 내용에 맞게 자동 설계. 원고와 대상 청중을 기준으로 "
            "PPT Master가 적합한 디자인 시스템을 결정하세요."
        )
    return (
        f"스타일 프리셋: {style['name']} (`{style['id']}`)\n"
        "아래 저장된 카이로스 디자인 시스템은 사용자 확정값입니다. "
        "색상·타이포그래피·레이아웃 규칙·이미지 방향·QA 규칙을 "
        "design_spec.md와 spec_lock.md에 그대로 투영하고 전체 덱에 적용하세요.\n"
        + json.dumps(brief, ensure_ascii=False, indent=2)
    )
