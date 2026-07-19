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
