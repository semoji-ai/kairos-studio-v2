import importlib
import sys
from pathlib import Path


def test_staged_ppt_master_measures_and_routes_hangul_correctly():
    scripts = (
        Path(__file__).parents[1]
        / "src-tauri"
        / "resources"
        / "ppt-master"
        / "skills"
        / "ppt-master"
        / "scripts"
    )
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
