"""세션별 사용자 산출물 폴더 관리.

에이전트 실행용 workspace_dir과 사용자가 결과를 모아 보는 output_dir을 분리한다.
프로바이더 샌드박스가 외부 output_dir 직접 쓰기를 막는 경우에도, 응답에 언급된
실제 파일을 채팅 완료 후 세션 폴더로 복사한다.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from core.artifacts import extract_artifacts


def _slug(title: str) -> str:
    value = re.sub(r"[^\w가-힣-]+", "-", title, flags=re.UNICODE).strip("-_")
    return value[:36] or "작업"


def session_dir(output_dir: str | None, session_id: int, title: str) -> Path | None:
    if not output_dir:
        return None
    root = Path(output_dir).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    prefix = f"session-{session_id}-"
    existing = sorted(path for path in root.glob(f"{prefix}*") if path.is_dir())
    target = existing[0] if existing else root / f"{prefix}{_slug(title)}"
    target.mkdir(parents=True, exist_ok=True)
    return target


def mirror_outputs(
    text: str,
    agent_workspace: str | None,
    target_dir: Path | None,
) -> list[Path]:
    """응답에 언급된 산출물을 세션 폴더에 최신본으로 복사한다."""
    if target_dir is None:
        return []
    copied: list[Path] = []
    for source in extract_artifacts(text, agent_workspace):
        try:
            source = source.resolve()
            target = (target_dir / source.name).resolve()
            if source == target:
                copied.append(target)
                continue
            target.relative_to(target_dir.resolve())
            shutil.copy2(source, target)
            copied.append(target)
        except (OSError, ValueError):
            continue
    return copied


def instruction(target_dir: Path | None) -> str:
    if target_dir is None:
        return ""
    return (
        "[산출물 저장 위치]\n"
        f"이 대화의 문서·이미지 등 최종 산출물은 가능하면 다음 폴더에 저장하세요: {target_dir}\n"
        "응답에는 사용자가 열 수 있도록 실제 파일의 절대경로를 Markdown 링크로 제공하세요."
    )
