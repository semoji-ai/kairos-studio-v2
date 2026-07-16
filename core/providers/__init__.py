from core.providers import claude, codex

_REGISTRY = {"claude": claude, "codex": codex}


def get(name: str):
    return _REGISTRY[name]
