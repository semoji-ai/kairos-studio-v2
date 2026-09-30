import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


import pytest


@pytest.fixture(autouse=True)
def _isolated_documents(tmp_path, monkeypatch):
    # 기본 산출물 폴더(문서/KS_output)가 실제 문서 폴더에 생기지 않게 모든 테스트를 격리
    monkeypatch.setenv("KAIROS_DOCUMENTS_DIR", str(tmp_path / "Documents"))
