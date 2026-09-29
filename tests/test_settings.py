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
