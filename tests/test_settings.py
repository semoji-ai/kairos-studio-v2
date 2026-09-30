import json

import pytest

from core import settings


@pytest.fixture(autouse=True)
def cfg_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("KAIROS_CONFIG_DIR", str(tmp_path))
    return tmp_path


def test_defaults_when_no_file():
    s = settings.load()
    assert s["default_provider"] == "claude"
    assert s["routing_rules_enabled"] is True
    assert s["codex_sandbox"] == "read-only"
    assert s["claude_permission_mode"] == "default"
    assert s["data_dir"]  # 존재만 확인 (기본 ~/.kairos-studio)


def test_save_merges_and_persists(cfg_dir):
    settings.save({"default_provider": "codex"})
    s = settings.load()
    assert s["default_provider"] == "codex"
    assert s["routing_rules_enabled"] is True  # 나머지는 기본값 유지
    raw = json.loads((cfg_dir / "settings.json").read_text())
    assert raw["default_provider"] == "codex"


def test_whitelist_rejects_bad_values():
    for patch in [{"default_provider": "gpt"},
                  {"codex_sandbox": "danger-full-access"},
                  {"claude_permission_mode": "bypassPermissions"},
                  {"routing_rules_enabled": "yes"}]:
        with pytest.raises(ValueError):
            settings.save(patch)


def test_unknown_keys_preserved(cfg_dir):
    settings.save({"future_key": {"nested": 1}})
    assert settings.load()["future_key"] == {"nested": 1}


def test_explicit_keys(cfg_dir):
    assert settings.explicit_keys() == set()
    settings.save({"default_provider": "codex"})
    assert "default_provider" in settings.explicit_keys()
    assert "codex_sandbox" not in settings.explicit_keys()


def test_workspace_dir_validation(tmp_path):
    settings.save({"workspace_dir": None})              # null 허용
    settings.save({"workspace_dir": str(tmp_path)})     # 존재하는 dir 허용
    with pytest.raises(ValueError):
        settings.save({"workspace_dir": str(tmp_path / "nope")})
    with pytest.raises(ValueError):
        settings.save({"workspace_dir": 123})


def test_output_dir_validation(tmp_path):
    settings.save({"output_dir": None})
    settings.save({"output_dir": str(tmp_path / "may-be-created-later")})
    with pytest.raises(ValueError):
        settings.save({"output_dir": 123})


def test_learning_recall_flag_validation():
    settings.save({"learning_recall_enabled": False})
    with pytest.raises(ValueError):
        settings.save({"learning_recall_enabled": "yes"})


def test_font_defaults_to_system():
    s = settings.load()
    assert s["font_body"] == "system"
    assert s["font_heading"] == "system"


def test_font_choice_persists_and_rejects_unknown():
    s = settings.save({"font_body": "pretendard", "font_heading": "gowun-batang"})
    assert (s["font_body"], s["font_heading"]) == ("pretendard", "gowun-batang")
    for patch in [{"font_body": "comic-sans"}, {"font_heading": "pretendard"},
                  {"font_body": "gowun-batang"}]:
        with pytest.raises(ValueError):
            settings.save(patch)


def test_font_invalid_stored_value_falls_back(cfg_dir):
    # 손으로 고쳤거나 이후 버전에서 빠진 글꼴이면 기본값으로 되돌린다
    (cfg_dir / "settings.json").write_text(
        json.dumps({"font_body": "removed-font", "font_heading": "maruburi"}))
    s = settings.load()
    assert s["font_body"] == "system"
    assert s["font_heading"] == "maruburi"


# ── 폴더 기본값 ─────────────────────────────────────────────


def _home(tmp_path, monkeypatch, documents=True):
    home = tmp_path / "home"
    (home / "Documents").mkdir(parents=True) if documents else home.mkdir(parents=True)
    monkeypatch.setattr(settings.Path, "home", lambda: home)
    monkeypatch.delenv("KAIROS_DOCUMENTS_DIR", raising=False)
    monkeypatch.setattr(settings.sys, "platform", "darwin")
    return home


def test_output_dir_defaults_to_documents_ks_output(tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch)
    assert settings.load()["output_dir"] == str(home / "Documents" / "KS_output")


def test_output_dir_falls_back_to_home_without_documents(tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch, documents=False)
    assert settings.load()["output_dir"] == str(home / "KS_output")


def test_workspace_defaults_only_when_installed(tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch)
    assert settings.load()["workspace_dir"] is None
    (home / "Documents" / "publish-agent").mkdir()
    assert settings.load()["workspace_dir"] == str(home / "Documents" / "publish-agent")


def test_explicitly_cleared_folders_stay_cleared(tmp_path, monkeypatch, cfg_dir):
    home = _home(tmp_path, monkeypatch)
    (home / "Documents" / "publish-agent").mkdir()
    settings.save({"output_dir": None, "workspace_dir": None})
    s = settings.load()
    assert s["output_dir"] is None and s["workspace_dir"] is None


def test_windows_documents_folder_from_registry(tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch)
    onedrive = tmp_path / "OneDrive" / "문서"
    onedrive.mkdir(parents=True)
    monkeypatch.setattr(settings.sys, "platform", "win32")
    monkeypatch.setattr(settings, "_windows_documents", lambda: str(onedrive))
    assert settings.load()["output_dir"] == str(onedrive / "KS_output")


def test_documents_dir_env_override(tmp_path, monkeypatch):
    target = tmp_path / "docs"
    target.mkdir()
    monkeypatch.setenv("KAIROS_DOCUMENTS_DIR", str(target))
    assert settings.load()["output_dir"] == str(target / "KS_output")
