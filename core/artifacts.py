"""인라인 아티팩트 감지·보존.

스펙: docs/superpowers/specs/2026-07-20-p2-artifacts-design.md

- extract_artifacts: 텍스트에서 파일 경로 후보를 정규식으로 뽑아 절대/워크스페이스
  상대 경로로 해석하고, 실제 존재하는 파일만 중복 제거해 반환하는 순수 함수.
- collect: extract_artifacts 결과를 data_dir/artifacts/{message_id}/로 복사하고
  채팅 content 파트 dict 리스트를 만든다. 실패는 파일 단위로 조용히 스킵.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_DOC_EXTS = {".md"}
_ALL_EXTS = _IMAGE_EXTS | _DOC_EXTS

_PATH_RE = re.compile(
    r"""[^\s"'`]+\.(?:png|jpe?g|webp|gif|md)""", re.IGNORECASE
)

_MAX_IMAGE_BYTES = 10 * 1024 * 1024
_MAX_DOC_BYTES = 1 * 1024 * 1024
_MAX_ARTIFACTS = 6


def extract_artifacts(text: str, workspace_dir: str | None) -> list[Path]:
    """텍스트 속 이미지/문서 경로 후보를 찾아 실재하는 파일 경로 리스트로 반환.

    해석 순서: 절대 경로 그대로 → 존재하지 않으면 workspace_dir 기준 상대 경로.
    둘 다 없으면 스킵. 중복 경로(resolve 기준)는 1회만.
    """
    found: list[Path] = []
    seen: set[Path] = set()
    for m in _PATH_RE.finditer(text):
        raw = m.group(0)
        candidate = Path(raw)
        resolved: Path | None = None
        if candidate.is_absolute() and candidate.is_file():
            resolved = candidate.resolve()
        elif workspace_dir:
            ws_candidate = Path(workspace_dir).expanduser() / raw
            if ws_candidate.is_file():
                resolved = ws_candidate.resolve()
        if resolved is None and not candidate.is_absolute():
            # 절대 경로가 아니면서 workspace_dir이 없거나 안 맞을 때: cwd 기준도 시도하지 않는다
            # (스펙: 절대 경로 그대로 → workspace 상대만).
            pass
        if resolved is None:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        found.append(resolved)
    return found


def _content_type(path: Path) -> str:
    return "image" if path.suffix.lower() in _IMAGE_EXTS else "document"


def _unique_dest(dest_dir: Path, filename: str) -> Path:
    dest = dest_dir / filename
    if not dest.exists():
        return dest
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    n = 2
    while True:
        candidate = dest_dir / f"{stem}-{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def collect(text: str, workspace_dir: str | None, data_dir: Path,
            message_id: int) -> list[dict]:
    """감지된 아티팩트를 data_dir/artifacts/{message_id}/로 복사하고 파트를 만든다.

    실패(권한, 크기 초과, data_dir 내부 자기참조 등)는 해당 파일만 조용히 스킵.
    최대 _MAX_ARTIFACTS개.
    """
    data_dir = Path(data_dir)
    artifacts_root = (data_dir / "artifacts").resolve()
    parts: list[dict] = []
    try:
        candidates = extract_artifacts(text, workspace_dir)
    except Exception:
        return []

    for src in candidates:
        if len(parts) >= _MAX_ARTIFACTS:
            break
        try:
            # artifacts 루트 내부 파일(이미 보존된 아티팩트 자기 참조)은 제외
            try:
                src.relative_to(artifacts_root)
                continue
            except ValueError:
                pass

            ctype = _content_type(src)
            size = src.stat().st_size
            limit = _MAX_IMAGE_BYTES if ctype == "image" else _MAX_DOC_BYTES
            if size > limit:
                continue

            dest_dir = artifacts_root / str(message_id)
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = _unique_dest(dest_dir, src.name)
            shutil.copy2(src, dest)

            artifact_rel = f"{message_id}/{dest.name}"
            part: dict = {"type": ctype, "artifact": artifact_rel}
            if ctype == "document":
                part["title"] = src.name
            parts.append(part)
        except Exception:
            continue

    return parts
