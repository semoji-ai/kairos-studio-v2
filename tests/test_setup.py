import zipfile

import pytest

from core.setup import cli_install_command, install_workspace


def test_cli_install_command_env_override(monkeypatch):
    monkeypatch.setenv("KAIROS_CLI_INSTALL_CMD", "python -c print(1)")
    assert cli_install_command() == ["python", "-c", "print(1)"]


def test_install_workspace_extracts_and_preserves_existing(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    zip_path = bundle / "publish_agent.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("skills/publish-write/SKILL.md", "# skill")

    dest_root = tmp_path / "dest"
    result = install_workspace(bundle, dest_root)
    ws = dest_root / "publish-agent"
    assert result == {"workspace_dir": str(ws), "existed": False}
    assert (ws / "skills" / "publish-write" / "SKILL.md").is_file()

    # 두번째 호출: 이미 존재하는 폴더는 보존(덮어쓰지 않음)
    (ws / "marker.txt").write_text("keep me")
    result2 = install_workspace(bundle, dest_root)
    assert result2 == {"workspace_dir": str(ws), "existed": True}
    assert (ws / "marker.txt").is_file()


def test_install_workspace_missing_zip_raises(tmp_path):
    bundle = tmp_path / "empty_bundle"
    bundle.mkdir()
    with pytest.raises(FileNotFoundError):
        install_workspace(bundle, tmp_path / "dest")


def test_install_workspace_rejects_zip_slip(tmp_path):
    bundle = tmp_path / "evil_bundle"
    bundle.mkdir()
    zip_path = bundle / "publish_agent.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        # crafted entry escaping the extraction dir via ".."
        evil = zipfile.ZipInfo("../evil.txt")
        zf.writestr(evil, "pwned")

    dest_root = tmp_path / "dest"
    with pytest.raises(ValueError):
        install_workspace(bundle, dest_root)
    # nothing should have leaked outside dest_root's parent
    assert not (tmp_path / "evil.txt").exists()


# ── 스킬 갱신 ──────────────────────────────────────────────

from core.setup import update_workspace, workspace_update_status  # noqa: E402


def _bundle(tmp_path, files: dict[str, str]):
    bundle = tmp_path / "bundle"
    bundle.mkdir(exist_ok=True)
    with zipfile.ZipFile(bundle / "publish_agent.zip", "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return bundle


def _workspace(tmp_path, files: dict[str, str]):
    ws = tmp_path / "ws"
    for name, text in files.items():
        p = ws / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return ws


def test_update_status_lists_changed_and_added(tmp_path):
    bundle = _bundle(tmp_path, {"CLAUDE.md": "new", "skills/a/SKILL.md": "same",
                                "skills/b/SKILL.md": "added"})
    ws = _workspace(tmp_path, {"CLAUDE.md": "old", "skills/a/SKILL.md": "same"})
    st = workspace_update_status(bundle, ws)
    assert st["available"] is True
    assert st["changed"] == ["CLAUDE.md"]
    assert st["added"] == ["skills/b/SKILL.md"]


def test_update_status_up_to_date(tmp_path):
    bundle = _bundle(tmp_path, {"skills/a/SKILL.md": "same"})
    ws = _workspace(tmp_path, {"skills/a/SKILL.md": "same"})
    st = workspace_update_status(bundle, ws)
    assert st["available"] is False
    assert st["changed"] == [] and st["added"] == []


def test_update_status_without_bundle_is_unavailable(tmp_path):
    ws = _workspace(tmp_path, {"skills/a/SKILL.md": "x"})
    empty = tmp_path / "empty"
    empty.mkdir()
    st = workspace_update_status(empty, ws)
    assert st["available"] is False
    assert st["reason"] == "no_bundle"


def test_update_status_git_workspace_is_skipped(tmp_path):
    bundle = _bundle(tmp_path, {"CLAUDE.md": "new"})
    ws = _workspace(tmp_path, {"CLAUDE.md": "old"})
    (ws / ".git").mkdir()
    st = workspace_update_status(bundle, ws)
    assert st["available"] is False
    assert st["reason"] == "git"


def test_update_status_protects_custom_files(tmp_path):
    bundle = _bundle(tmp_path, {"skills/r/references/custom-rubric.md": "core"})
    ws = _workspace(tmp_path, {"skills/r/references/custom-rubric.md": "church"})
    st = workspace_update_status(bundle, ws)
    assert st["available"] is False
    assert st["changed"] == []


def test_update_backs_up_writes_and_preserves_user_data(tmp_path):
    bundle = _bundle(tmp_path, {"CLAUDE.md": "new", "skills/b/SKILL.md": "added",
                                "skills/r/custom-x.md": "core"})
    ws = _workspace(tmp_path, {"CLAUDE.md": "old", "wiki/sermons/a.md": "원고",
                               "skills/old/SKILL.md": "removed upstream",
                               "skills/r/custom-x.md": "church"})
    res = update_workspace(bundle, ws)
    assert res["updated"] == ["CLAUDE.md", "skills/b/SKILL.md"]
    assert (ws / "CLAUDE.md").read_text(encoding="utf-8") == "new"
    assert (ws / "skills/b/SKILL.md").read_text(encoding="utf-8") == "added"
    # 사용자 데이터·새 버전에서 빠진 파일·custom 파일은 그대로
    assert (ws / "wiki/sermons/a.md").read_text(encoding="utf-8") == "원고"
    assert (ws / "skills/old/SKILL.md").is_file()
    assert (ws / "skills/r/custom-x.md").read_text(encoding="utf-8") == "church"
    # 바뀐 파일만 원래 경로 구조로 백업
    backup = ws / res["backup_dir"]
    assert backup.parent.name == ".kairos-backup"
    assert (backup / "CLAUDE.md").read_text(encoding="utf-8") == "old"
    assert not (backup / "skills/b/SKILL.md").exists()
    assert workspace_update_status(bundle, ws)["available"] is False


def test_update_refuses_git_workspace(tmp_path):
    bundle = _bundle(tmp_path, {"CLAUDE.md": "new"})
    ws = _workspace(tmp_path, {"CLAUDE.md": "old"})
    (ws / ".git").mkdir()
    with pytest.raises(ValueError):
        update_workspace(bundle, ws)
    assert (ws / "CLAUDE.md").read_text(encoding="utf-8") == "old"


def test_update_rejects_zip_slip(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    with zipfile.ZipFile(bundle / "publish_agent.zip", "w") as zf:
        zf.writestr(zipfile.ZipInfo("../evil.txt"), "pwned")
    ws = _workspace(tmp_path, {"CLAUDE.md": "old"})
    with pytest.raises(ValueError):
        update_workspace(bundle, ws)
    assert not (tmp_path / "evil.txt").exists()
