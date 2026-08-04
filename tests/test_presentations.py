import io
import json
import time
import zipfile
from pathlib import Path

from core.presentation_fleet import (
    apply_image_style_lock,
    convert_manifest,
    validate_image_style_lock,
)
from core.presentations import PresentationManager, normalize_document
from core.presentation_styles import (
    default_image_style,
    default_presentation_style,
    get_image_style,
    image_style_prompt,
    get_presentation_style,
    presentation_style_prompt,
)


def _docx(path: Path):
    document = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
 <w:body>
  <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>학습 목표</w:t></w:r></w:p>
  <w:p><w:r><w:t>핵심 개념 그림</w:t></w:r><w:r><a:blip r:embed="rId1"/></w:r></w:p>
 </w:body>
</w:document>"""
    rels = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Target="media/image1.png" Type="image"/>
</Relationships>"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", document)
        zf.writestr("word/_rels/document.xml.rels", rels)
        zf.writestr("word/media/image1.png", b"\x89PNG\r\nfake")


def test_docx_normalization_preserves_text_and_image(tmp_path):
    source = tmp_path / "lecture.docx"
    _docx(source)
    result = normalize_document(source, tmp_path / "normalized")
    md = (tmp_path / "normalized" / "lecture.md").read_text(encoding="utf-8")
    assert "# 학습 목표" in md
    assert "핵심 개념 그림" in md
    assert "![핵심 개념 그림](assets/asset-0001.png)" in md
    assert len(result["assets"]) == 1
    assert (tmp_path / "normalized" / "assets" / "asset-0001.png").is_file()


def test_hwpx_normalization_extracts_bindata(tmp_path):
    source = tmp_path / "lecture.hwpx"
    xml = """<sec><p><run><t>한글 강의 본문</t></run></p></sec>"""
    with zipfile.ZipFile(source, "w") as zf:
        zf.writestr("Contents/section0.xml", xml)
        zf.writestr("BinData/picture.jpg", b"\xff\xd8fake")
    result = normalize_document(source, tmp_path / "normalized")
    md = (tmp_path / "normalized" / "lecture.md").read_text(encoding="utf-8")
    assert "한글 강의 본문" in md
    assert len(result["assets"]) == 1
    assert result["assets"][0]["path"].endswith(".jpg")


def test_fleet_manifest_adapter(tmp_path):
    manifest = tmp_path / "image_prompts.json"
    manifest.write_text(json.dumps({
        "items": [{
            "filename": "cover.png",
            "aspect_ratio": "16:9",
            "image_size": "2K",
            "prompt": "교육용 표지",
            "status": "Pending",
        }]
    }, ensure_ascii=False), encoding="utf-8")
    payload, items = convert_manifest(manifest, tmp_path / "fleet.jsonl")
    assert payload["items"][0]["filename"] == "cover.png"
    assert items == [{
        "id": "ppt-001", "prompt": "교육용 표지", "ar": "16:9",
        "size": "1792x1024", "output_path": "cover.png",
    }]


def test_fleet_normalizes_no_text_prompt_for_prompt_kit(tmp_path):
    manifest = tmp_path / "image_prompts.json"
    manifest.write_text(json.dumps({
        "items": [{
            "filename": "scene.png",
            "text_policy": "editable_svg_only",
                "prompt": (
                "# 1. Scene\nA caring group without staged sentiment.\n"
                "# 2. Camera\nEye-level composition.\n"
                "# 3. Lighting\nSoft window light.\n"
                "# 6. Text-in-image\nSurfaces are free of lettering. AR 16:9"
                ),
        }]
    }), encoding="utf-8")

    payload, items = convert_manifest(manifest, tmp_path / "fleet.jsonl")

    prompt = items[0]["prompt"]
    assert "Text-in-image:" not in prompt
    assert "without staged sentiment" not in prompt
    assert "free of lettering" not in prompt
    assert "clean unmarked surfaces" in prompt
    assert "Visual policy:" in prompt
    assert prompt.startswith("Scene:")
    assert "Camera:" in prompt
    assert "Lighting:" in prompt
    assert payload["items"][0]["prompt"] == prompt


def test_manager_fake_job_completes(tmp_path, monkeypatch):
    monkeypatch.setenv("KAIROS_PRESENTATION_FAKE", "1")
    manager = PresentationManager(tmp_path)
    source = tmp_path / "lecture.docx"
    _docx(source)
    job = manager.create(source.name, source.read_bytes(), {"provider": "codex"})
    deadline = time.time() + 5
    while time.time() < deadline:
        current = manager.get(job["id"])
        if current and current["status"] in {"completed", "failed"}:
            break
        time.sleep(0.05)
    assert current["status"] == "completed", current
    assert Path(current["result"]).is_file()
    assert manager.list()[0]["id"] == job["id"]


def test_manager_retries_failed_job(tmp_path, monkeypatch):
    monkeypatch.setenv("KAIROS_PRESENTATION_FAKE", "1")
    manager = PresentationManager(tmp_path)
    source = tmp_path / "lecture.md"
    source.write_text("# lecture", encoding="utf-8")
    job = manager.create(source.name, source.read_bytes(), {})
    deadline = time.time() + 5
    while time.time() < deadline:
        current = manager.get(job["id"])
        if current and current["status"] == "completed":
            break
        time.sleep(0.05)
    manager._write_status(job["id"], status="failed", error="forced")
    retried = manager.retry(job["id"])
    assert retried["status"] in {"queued", "running", "completed"}
    deadline = time.time() + 5
    while time.time() < deadline:
        current = manager.get(job["id"])
        if current and current["status"] == "completed":
            break
        time.sleep(0.05)
    assert current["status"] == "completed"


def test_external_worker_enqueues_until_worker_claims_job(tmp_path, monkeypatch):
    monkeypatch.setenv("KAIROS_PRESENTATION_FAKE", "1")
    manager = PresentationManager(tmp_path, external_worker=True)
    source = tmp_path / "lecture.md"
    source.write_text("# lecture", encoding="utf-8")
    job = manager.create(source.name, source.read_bytes(), {})
    time.sleep(0.1)
    assert manager.get(job["id"])["status"] == "queued"

    completed = manager.run_job(job["id"])
    assert completed["status"] == "completed"
    assert Path(completed["result"]).is_file()


def test_agent_prompt_splits_image_plan_from_ppt_execution(tmp_path):
    args = (
        tmp_path / "project",
        tmp_path / "ppt-master",
        tmp_path / "presentation_fleet.py",
        tmp_path / "codex_imagegen_runner.py",
        tmp_path / "prompt-kit",
        {
            "use_ai_images": True,
            "slide_count": 10,
            "style_preset": "quiet-cinematic-editorial",
        },
    )

    plan = PresentationManager._agent_prompt(*args, phase="plan")
    execute = PresentationManager._agent_prompt(*args, phase="execute")

    assert "KAIROS_IMAGE_PLAN_READY" in plan
    assert "Fleet, imagegen, image_gen.py를 실행하지 말고" in plan
    assert "SVG나 PPTX도 아직 만들지 마세요" in plan
    assert "독립 백그라운드 워커" in execute
    assert "Fleet, imagegen, image_gen.py를 다시 실행하지 마세요" in execute
    assert "svg_to_pptx.py를 실행하거나 PPTX를 만들지 마세요" in execute
    assert "KAIROS_PPT_SOURCES_READY" in execute
    assert "Noto Sans KR" in execute
    assert "FLOW·단계·수렴 다이어그램" in execute
    assert "y = circle cy + 약 0.32 × font-size" in execute
    assert "Quiet Cinematic Editorial" in execute
    assert "다중 둥근 카드 그리드" in execute
    assert "실제 PPTX를 1280×720 PNG로 렌더링" in execute


def test_quiet_cinematic_editorial_is_saved_default_style():
    assert default_presentation_style() == "quiet-cinematic-editorial"
    style = get_presentation_style(None)
    assert style["design_brief"]["palette"]["primary"] == "#17231F"
    assert style["design_brief"]["typography"]["family"].startswith("Noto Sans KR")
    prompt = presentation_style_prompt(style["id"])
    assert "연속된 두 페이지에 같은 구성을 반복하지 않는다" in prompt
    assert "FLOW는 카드 나열이 아니라" in prompt


def test_image_style_is_selected_and_locked_consistently():
    assert default_image_style() == "cinematic-documentary"
    style = get_image_style("editorial-illustration")
    payload = {
        "items": [
            {"prompt": "Scene: a teacher in a classroom. AR 16:9", "aspect_ratio": "16:9"},
            {"prompt": "Scene: learners in discussion. AR 16:9", "aspect_ratio": "16:9"},
        ]
    }
    lock = {
        "image_style_id": style["id"],
        "visual_dna": style["visual_dna"],
    }
    apply_image_style_lock(payload, lock)
    validate_image_style_lock(payload, lock)
    assert payload["items"][0]["visual_dna"] == payload["items"][1]["visual_dna"]
    assert payload["items"][0]["prompt"].endswith("AR 16:9")
    assert f"Visual DNA: {style['visual_dna']}" in payload["items"][1]["prompt"]
    assert "변경할 수 없는 고정 문자열" in image_style_prompt(style["id"])


def test_manager_reads_utf8_bom_status_history(tmp_path):
    manager = PresentationManager(tmp_path, external_worker=True)
    job_dir = manager.root / "abc123abc123"
    job_dir.mkdir()
    (job_dir / "status.json").write_text(
        json.dumps(
            {
                "id": "abc123abc123",
                "title": "보존된 PPT",
                "created_at": "2026-07-24T00:00:00+00:00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8-sig",
    )
    assert manager.get("abc123abc123")["title"] == "보존된 PPT"
    assert manager.list()[0]["id"] == "abc123abc123"
