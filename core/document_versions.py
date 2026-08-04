"""Markdown 문서 수정본 저장과 버전 생성."""
from __future__ import annotations

import difflib
from datetime import datetime
from pathlib import Path

_MAX_DOCUMENT_BYTES = 2 * 1024 * 1024


def resolve_editable(path_text: str, roots: list[Path]) -> Path:
    candidate = Path(path_text).expanduser().resolve()
    editable = (
        candidate.suffix.lower() in {".md", ".markdown"}
        or candidate.name.lower().endswith(".review.json")
    )
    if not editable:
        raise ValueError("only Markdown and review JSON documents are editable")
    if not any(_within(candidate, root.resolve()) for root in roots):
        raise ValueError("document is outside configured workspaces")
    if not candidate.is_file():
        raise ValueError("document not found")
    if candidate.stat().st_size > _MAX_DOCUMENT_BYTES:
        raise ValueError("document is too large")
    return candidate


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def save_version(path: Path, edited: str) -> dict:
    original = path.read_text(encoding="utf-8")
    if original == edited:
        return {
            "changed": False, "path": str(path), "version_path": None,
            "original": original, "edited": edited, "diff": "",
            "additions": 0, "deletions": 0,
        }

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    version_dir = path.parent / ".kairos-versions" / path.stem
    version_dir.mkdir(parents=True, exist_ok=True)
    version_path = version_dir / f"{stamp}-before{path.suffix}"
    version_path.write_text(original, encoding="utf-8")
    path.write_text(edited, encoding="utf-8")

    diff_lines = list(difflib.unified_diff(
        original.splitlines(), edited.splitlines(),
        fromfile="AI 원문", tofile="목사님 수정", lineterm="",
    ))
    additions = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
    deletions = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))
    return {
        "changed": True, "path": str(path), "version_path": str(version_path),
        "original": original, "edited": edited, "diff": "\n".join(diff_lines),
        "additions": additions, "deletions": deletions,
    }
