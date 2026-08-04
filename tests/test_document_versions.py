from pathlib import Path

import pytest

from core.document_versions import resolve_editable, save_version


def test_save_version_preserves_original_and_writes_edit(tmp_path):
    doc = tmp_path / "sermon.md"
    doc.write_text("AI 원문\n둘째 줄\n", encoding="utf-8")

    result = save_version(doc, "목사님 수정\n둘째 줄\n새 문장\n")

    assert result["changed"] is True
    assert result["additions"] == 2
    assert result["deletions"] == 1
    assert Path(result["version_path"]).read_text(encoding="utf-8") == "AI 원문\n둘째 줄\n"
    assert doc.read_text(encoding="utf-8") == "목사님 수정\n둘째 줄\n새 문장\n"
    assert "AI 원문" in result["diff"] and "목사님 수정" in result["diff"]


def test_resolve_editable_rejects_outside_root_and_non_markdown(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("no", encoding="utf-8")
    text = root / "notes.txt"
    text.write_text("no", encoding="utf-8")

    with pytest.raises(ValueError):
        resolve_editable(str(outside), [root])
    with pytest.raises(ValueError):
        resolve_editable(str(text), [root])
