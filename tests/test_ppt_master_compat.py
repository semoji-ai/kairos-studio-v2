import importlib
import sys
from pathlib import Path

import pytest

SCRIPTS = (
    Path(__file__).parents[1]
    / "src-tauri"
    / "resources"
    / "ppt-master"
    / "skills"
    / "ppt-master"
    / "scripts"
)


# ppt-master는 scripts/build-resources.* 가 릴리스 빌드 때만 스테이징한다
# (gitignore). 스테이징 전 체크아웃에서는 검사할 대상이 없으므로 건너뛴다.
@pytest.mark.skipif(not (SCRIPTS / "svg_to_pptx").is_dir(),
                    reason="ppt-master 미스테이징 — scripts/build-resources.* 실행 후 검사")
def test_staged_ppt_master_measures_and_routes_hangul_correctly():
    scripts = SCRIPTS
    sys.path.insert(0, str(scripts))
    try:
        utils = importlib.import_module("svg_to_pptx.drawingml.utils")
        assert utils.is_cjk_char("한")
        assert utils.detect_text_lang("한글") == "ko-KR"
        assert utils.estimate_text_width("한글", 20) == 40
        fonts = utils.parse_font_family(
            "Noto Sans KR, Aptos, Arial, sans-serif"
        )
        assert utils.resolve_text_run_fonts("한글", fonts)["ea"] == "Noto Sans KR"
    finally:
        sys.path.remove(str(scripts))
