import pytest

from core.router import route

GOLDEN = [
    # (입력, 기대 provider)
    ("@codex 이 함수 정리해줘", "codex"),
    ("@claude 코드 리뷰해줘", "claude"),          # 멘션이 규칙을 이긴다
    ("오늘 유튜브 기획 아이디어 줘", "claude"),
    ("core/server.py 버그 고쳐줘", "codex"),       # 파일 경로
    ("```python\nprint(1)\n``` 이거 왜 안 돼?", "codex"),  # 코드펜스
    ("git rebase 하다 꼬였어, 터미널에서 풀어줘", "codex"),
    ("점심 뭐 먹을까", "claude"),
    ("이 에러 스택트레이스 봐줘: Traceback (most recent call last)", "codex"),
]


@pytest.mark.parametrize("text,expected", GOLDEN)
def test_golden_routing(text, expected):
    provider, _ = route(text)
    assert provider == expected


def test_mention_is_stripped():
    provider, cleaned = route("@codex 이 함수 정리해줘")
    assert provider == "codex"
    assert cleaned == "이 함수 정리해줘"


def test_plain_text_passes_through():
    _, cleaned = route("안녕하세요")
    assert cleaned == "안녕하세요"


def test_rules_disabled_uses_default_provider():
    cfg = {"routing_rules_enabled": False, "default_provider": "codex"}
    assert route("점심 뭐 먹을까", cfg)[0] == "codex"
    assert route("core/server.py 고쳐줘", cfg)[0] == "codex"  # 규칙 꺼짐


def test_mention_beats_disabled_rules():
    cfg = {"routing_rules_enabled": False, "default_provider": "codex"}
    provider, cleaned = route("@claude 인사해", cfg)
    assert provider == "claude" and cleaned == "인사해"


def test_default_provider_when_no_signal():
    cfg = {"routing_rules_enabled": True, "default_provider": "codex"}
    assert route("점심 뭐 먹을까", cfg)[0] == "codex"
    assert route("git rebase 꼬였어", cfg)[0] == "codex"
