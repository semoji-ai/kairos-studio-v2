"""Lecture document intake and PPT Master orchestration."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

from core import providers
from core.presentation_styles import (
    default_image_style,
    default_presentation_style,
    get_image_style,
    get_presentation_style,
    image_style_prompt,
    list_image_styles,
    list_presentation_styles,
    presentation_style_prompt,
)

_SUPPORTED = {".pdf", ".docx", ".hwp", ".hwpx", ".md", ".markdown"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff",
               ".webp", ".svg", ".emf", ".wmf"}
_JOBS_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z가-힣._-]+", "-", Path(name).name).strip(".-")
    return cleaned[:120] or "lecture"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _write_asset(src: bytes, suffix: str, assets_dir: Path, index: int,
                 source: str, page: int | None = None,
                 caption: str = "") -> dict:
    suffix = suffix.lower()
    if not suffix.startswith("."):
        suffix = "." + suffix
    if suffix not in _IMAGE_EXTS:
        suffix = ".bin"
    digest = hashlib.sha256(src).hexdigest()
    for existing in assets_dir.glob("*"):
        try:
            if hashlib.sha256(existing.read_bytes()).hexdigest() == digest:
                path = existing
                break
        except OSError:
            pass
    else:
        path = assets_dir / f"asset-{index:04d}{suffix}"
        path.write_bytes(src)
    return {
        "id": path.stem,
        "path": f"assets/{path.name}",
        "source_file": source,
        "page": page,
        "caption": caption,
        "kind": "image",
        "sha256": digest,
    }


def _extract_docx(source: Path, out_dir: Path) -> tuple[str, list[dict]]:
    assets_dir = out_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source) as zf:
        document = ET.fromstring(zf.read("word/document.xml"))
        rels: dict[str, str] = {}
        rel_name = "word/_rels/document.xml.rels"
        if rel_name in zf.namelist():
            rel_root = ET.fromstring(zf.read(rel_name))
            for rel in rel_root:
                rid = rel.attrib.get("Id")
                target = rel.attrib.get("Target", "")
                if rid and target:
                    rels[rid] = target.replace("\\", "/")

        lines: list[str] = []
        assets: list[dict] = []
        asset_index = 1
        body = next((e for e in document.iter() if _local(e.tag) == "body"), document)
        for child in body:
            kind = _local(child.tag)
            if kind == "p":
                text = "".join((n.text or "") for n in child.iter() if _local(n.tag) == "t").strip()
                style = ""
                for node in child.iter():
                    if _local(node.tag) == "pStyle":
                        style = next((v for k, v in node.attrib.items()
                                      if _local(k) == "val"), "")
                        break
                if text:
                    if style.lower().startswith(("title", "heading")):
                        digits = re.findall(r"\d+", style)
                        level = min(6, int(digits[0]) if digits else 1)
                        lines.append("#" * level + " " + text)
                    else:
                        lines.append(text)

                for node in child.iter():
                    if _local(node.tag) not in {"blip", "imagedata"}:
                        continue
                    rid = next((v for k, v in node.attrib.items()
                                if _local(k) in {"embed", "id"}), None)
                    target = rels.get(rid or "")
                    if not target:
                        continue
                    member = target.lstrip("/")
                    if not member.startswith("word/"):
                        member = "word/" + member.replace("../", "")
                    if member not in zf.namelist():
                        continue
                    caption = text
                    asset = _write_asset(zf.read(member), Path(member).suffix, assets_dir,
                                         asset_index, source.name, caption=caption)
                    asset_index += 1
                    assets.append(asset)
                    lines.append(f"![{caption or asset['id']}]({asset['path']})")
                if text or any(_local(n.tag) in {"blip", "imagedata"} for n in child.iter()):
                    lines.append("")
            elif kind == "tbl":
                rows = []
                for row in (n for n in child.iter() if _local(n.tag) == "tr"):
                    cells = []
                    for cell in (n for n in row if _local(n.tag) == "tc"):
                        cells.append(" ".join((n.text or "") for n in cell.iter()
                                              if _local(n.tag) == "t").strip())
                    if cells:
                        rows.append(cells)
                if rows:
                    width = max(len(r) for r in rows)
                    rows = [r + [""] * (width - len(r)) for r in rows]
                    lines.append("| " + " | ".join(rows[0]) + " |")
                    lines.append("| " + " | ".join(["---"] * width) + " |")
                    lines.extend("| " + " | ".join(r) + " |" for r in rows[1:])
                    lines.append("")
    return "\n".join(lines).strip() + "\n", assets


def _extract_hwpx(source: Path, out_dir: Path) -> tuple[str, list[dict]]:
    assets_dir = out_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    assets: list[dict] = []
    with zipfile.ZipFile(source) as zf:
        xml_names = sorted(n for n in zf.namelist()
                           if n.lower().endswith(".xml") and "section" in n.lower())
        for xml_name in xml_names:
            root = ET.fromstring(zf.read(xml_name))
            for paragraph in (n for n in root.iter() if _local(n.tag) == "p"):
                text = "".join((n.text or "") for n in paragraph.iter()
                               if _local(n.tag) in {"t", "text"}).strip()
                if text:
                    lines.append(text)
                    lines.append("")
        image_names = [n for n in zf.namelist()
                       if "/bindata/" in ("/" + n.lower())
                       and Path(n).suffix.lower() in _IMAGE_EXTS]
        for i, member in enumerate(image_names, 1):
            asset = _write_asset(zf.read(member), Path(member).suffix, assets_dir,
                                 i, source.name)
            assets.append(asset)
    if assets:
        lines.extend(["", "## 원본 문서 이미지"])
        lines.extend(f"![{a['id']}]({a['path']})" for a in assets)
    return "\n".join(lines).strip() + "\n", assets


def _convert_hwp_to_hwpx(source: Path, target: Path) -> bool:
    hwp5txt = shutil.which("hwp5txt")
    if hwp5txt:
        result = subprocess.run([hwp5txt, str(source)], capture_output=True,
                                encoding="utf-8", errors="replace", timeout=120)
        if result.returncode == 0 and result.stdout.strip():
            target.with_suffix(".txt").write_text(result.stdout, encoding="utf-8")
            return False
    if os.name != "nt":
        return False
    escaped_in = str(source.resolve()).replace("'", "''")
    escaped_out = str(target.resolve()).replace("'", "''")
    script = (
        "$h=New-Object -ComObject HWPFrame.HwpObject;"
        "$h.RegisterModule('FilePathCheckDLL','FilePathCheckerModuleExample');"
        f"$ok=$h.Open('{escaped_in}','HWP','forceopen:true');"
        f"if($ok){{$h.SaveAs('{escaped_out}','HWPX');}};"
        "$h.Quit();"
        "if(-not $ok){exit 2}"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=180,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and target.is_file()


def _extract_pdf(source: Path, out_dir: Path) -> tuple[str, list[dict]]:
    assets_dir = out_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    assets: list[dict] = []
    try:
        import fitz  # type: ignore
        doc = fitz.open(source)
        asset_index = 1
        for page_no, page in enumerate(doc, 1):
            lines.append(f"## 원본 {page_no}쪽")
            page_dict = page.get_text("dict")
            for block in page_dict.get("blocks", []):
                if block.get("type") == 0:
                    text = "\n".join(
                        "".join(span.get("text", "") for span in line.get("spans", []))
                        for line in block.get("lines", [])
                    ).strip()
                    if text:
                        lines.append(text)
                elif block.get("type") == 1 and block.get("image"):
                    asset = _write_asset(block["image"], block.get("ext", "png"),
                                         assets_dir, asset_index, source.name,
                                         page=page_no)
                    asset["bbox"] = block.get("bbox")
                    asset_index += 1
                    assets.append(asset)
                    lines.append(f"![{asset['id']}]({asset['path']})")
            lines.append("")
        doc.close()
        return "\n".join(lines).strip() + "\n", assets
    except ImportError:
        pass

    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:
        raise RuntimeError("PDF 변환에는 PyMuPDF 또는 pypdf가 필요합니다") from exc
    reader = PdfReader(str(source))
    asset_index = 1
    for page_no, page in enumerate(reader.pages, 1):
        lines.extend([f"## 원본 {page_no}쪽", page.extract_text() or ""])
        for image in getattr(page, "images", []):
            suffix = Path(getattr(image, "name", "")).suffix or ".png"
            asset = _write_asset(image.data, suffix, assets_dir, asset_index,
                                 source.name, page=page_no)
            asset_index += 1
            assets.append(asset)
            lines.append(f"![{asset['id']}]({asset['path']})")
        lines.append("")
    return "\n".join(lines).strip() + "\n", assets


def normalize_document(source: Path, out_dir: Path) -> dict:
    suffix = source.suffix.lower()
    if suffix not in _SUPPORTED:
        raise ValueError(f"지원하지 않는 파일 형식입니다: {suffix}")
    out_dir.mkdir(parents=True, exist_ok=True)
    if suffix in {".md", ".markdown"}:
        text, assets = source.read_text(encoding="utf-8"), []
    elif suffix == ".docx":
        text, assets = _extract_docx(source, out_dir)
    elif suffix == ".hwpx":
        text, assets = _extract_hwpx(source, out_dir)
    elif suffix == ".hwp":
        converted = out_dir / (source.stem + ".hwpx")
        if not _convert_hwp_to_hwpx(source, converted):
            txt = converted.with_suffix(".txt")
            if txt.is_file():
                text, assets = txt.read_text(encoding="utf-8"), []
            else:
                raise RuntimeError("HWP 변환 실패: 한컴오피스 또는 hwp5txt가 필요합니다")
        else:
            text, assets = _extract_hwpx(converted, out_dir)
    else:
        text, assets = _extract_pdf(source, out_dir)

    md_path = out_dir / "lecture.md"
    md_path.write_text(text, encoding="utf-8")
    manifest = {
        "source": source.name,
        "markdown": md_path.name,
        "assets": assets,
        "created_at": _now(),
    }
    (out_dir / "assets.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


class PresentationManager:
    def __init__(self, data_dir: Path, bundle_dir: Path | None = None,
                 external_worker: bool | None = None):
        self.root = data_dir / "presentations"
        self.root.mkdir(parents=True, exist_ok=True)
        self.bundle_dir = bundle_dir
        self.external_worker = (
            os.environ.get("KAIROS_PRESENTATION_EXTERNAL_WORKER") == "1"
            if external_worker is None else external_worker
        )
        self._stream_logs: dict[str, tuple[list[str], str]] = {}

    def _engine_dir(self, name: str) -> Path | None:
        env = os.environ.get(f"KAIROS_{name.upper().replace('-', '_')}_DIR")
        candidates = [Path(env).expanduser()] if env else []
        if self.bundle_dir:
            candidates.append(self.bundle_dir / name)
        candidates.append(Path(__file__).resolve().parent.parent / "vendor" / name)
        candidates.append(Path(__file__).resolve().parent.parent.parent / name)
        if os.name == "nt":
            candidates.append(Path("D:/projects") / name)
        return next((p.resolve() for p in candidates if p.is_dir()), None)

    def engines(self) -> dict:
        ppt = self._engine_dir("ppt-master")
        fleet = self._engine_dir("codex-fleet")
        prompt_kit = self._engine_dir("gongnyang-prompt-kit")
        worker = self.worker_status()
        return {
            "ppt_master": {"available": bool(ppt), "path": str(ppt) if ppt else None},
            "codex_fleet": {"available": bool(fleet), "path": str(fleet) if fleet else None},
            "prompt_kit": {"available": bool(prompt_kit), "path": str(prompt_kit) if prompt_kit else None},
            "worker": worker,
            "styles": list_presentation_styles(),
            "default_style": default_presentation_style(),
            "image_styles": list_image_styles(),
            "default_image_style": default_image_style(),
        }

    def worker_status(self) -> dict:
        path = self.root / "worker.json"
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            heartbeat = datetime.fromisoformat(str(state["heartbeat"]))
            alive = (datetime.now(timezone.utc) - heartbeat).total_seconds() < 10
            if not alive and state.get("state") == "working":
                try:
                    alive = _pid_alive(int(state["pid"]))
                except (TypeError, ValueError):
                    alive = False
            return {**state, "available": alive}
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            return {"available": not self.external_worker}

    def _job_dir(self, job_id: str) -> Path:
        return self.root / job_id

    def _status_path(self, job_id: str) -> Path:
        return self._job_dir(job_id) / "status.json"

    def _write_status(self, job_id: str, **patch) -> dict:
        with _JOBS_LOCK:
            path = self._status_path(job_id)
            current = json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else {}
            current.update(patch)
            current["updated_at"] = _now()
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
            return current

    def get(self, job_id: str) -> dict | None:
        if not re.fullmatch(r"[0-9a-f]{12}", job_id):
            return None
        path = self._status_path(job_id)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return None

    def list(self) -> list[dict]:
        jobs = []
        for path in self.root.glob("*/status.json"):
            try:
                jobs.append(json.loads(path.read_text(encoding="utf-8-sig")))
            except (OSError, json.JSONDecodeError):
                pass
        return sorted(jobs, key=lambda j: j.get("created_at", ""), reverse=True)

    def create(self, filename: str, content: bytes, options: dict) -> dict:
        suffix = Path(filename).suffix.lower()
        if suffix not in _SUPPORTED:
            raise ValueError("PDF, DOCX, HWP, HWPX, MD 파일만 지원합니다")
        if not content:
            raise ValueError("빈 파일입니다")
        if len(content) > 100 * 1024 * 1024:
            raise ValueError("파일은 100MB 이하여야 합니다")
        style = get_presentation_style(str(options.get("style_preset") or ""))
        options = dict(options)
        options["style_preset"] = style["id"]
        image_style = get_image_style(str(options.get("image_style") or ""))
        options["image_style"] = image_style["id"]
        if not str(options.get("tone") or "").strip():
            options["tone"] = style.get("tone") or "명료하고 현대적인 교육 자료"
        job_id = uuid.uuid4().hex[:12]
        job_dir = self._job_dir(job_id)
        upload_dir = job_dir / "upload"
        upload_dir.mkdir(parents=True)
        safe_name = _safe_name(filename)
        source = upload_dir / safe_name
        source.write_bytes(content)
        status = self._write_status(
            job_id,
            id=job_id,
            title=str(options.get("title") or source.stem)[:120],
            source_name=safe_name,
            status="queued",
            stage="업로드 완료",
            progress=5,
            provider=options.get("provider", "codex"),
            options=options,
            created_at=_now(),
            log=[],
            result=None,
            error=None,
        )
        self._dispatch(job_id, source, options)
        return status

    def retry(self, job_id: str) -> dict:
        current = self.get(job_id)
        if not current:
            raise ValueError("작업을 찾을 수 없습니다")
        if current.get("status") not in {"failed"}:
            raise ValueError("실패한 작업만 재시도할 수 있습니다")
        source = self._job_dir(job_id) / "upload" / str(current["source_name"])
        if not source.is_file():
            raise ValueError("원본 업로드 파일을 찾을 수 없습니다")
        workspace = self._job_dir(job_id) / "workspace"
        if workspace.is_dir():
            shutil.rmtree(workspace)
        self._write_status(job_id, status="queued", stage="재시도 대기 중", progress=5,
                           error=None, log=list(current.get("log") or []) + ["작업 재시도\n"])
        self._dispatch(job_id, source, dict(current.get("options") or {}))
        return self.get(job_id) or current

    def _dispatch(self, job_id: str, source: Path, options: dict):
        if self.external_worker:
            return
        threading.Thread(
            target=self._run, args=(job_id, source, options), daemon=True,
        ).start()

    def run_job(self, job_id: str, recovered: bool = False) -> dict:
        current = self.get(job_id)
        if not current:
            raise ValueError("작업을 찾을 수 없습니다")
        if current.get("status") not in {"queued", "running"}:
            return current
        source = self._job_dir(job_id) / "upload" / str(current["source_name"])
        if not source.is_file():
            self._write_status(
                job_id, status="failed", stage="실패",
                error="원본 업로드 파일을 찾을 수 없습니다",
            )
            return self.get(job_id) or current
        if recovered:
            workspace = self._job_dir(job_id) / "workspace"
            if workspace.is_dir():
                shutil.rmtree(workspace)
        self._write_status(
            job_id, status="running", stage="백그라운드 워커가 작업 시작",
            worker_pid=os.getpid(), error=None,
        )
        self._run(job_id, source, dict(current.get("options") or {}))
        return self.get(job_id) or current

    def _log(self, job_id: str, text: str):
        current = self.get(job_id) or {}
        logs = list(current.get("log") or [])
        logs.append(text[-2000:] + "\n")
        self._write_status(job_id, log=logs[-80:])

    def _begin_stream_log(self, job_id: str):
        current = self.get(job_id) or {}
        self._stream_logs[job_id] = (list(current.get("log") or [])[-79:], "")

    def _stream_log(self, job_id: str, text: str, project: Path, slide_count: int):
        base, accumulated = self._stream_logs.get(job_id, ([], ""))
        accumulated = (accumulated + text)[-12000:]
        self._stream_logs[job_id] = (base, accumulated)
        current = self.get(job_id) or {}
        progress = int(current.get("progress") or 40)
        stage = str(current.get("stage") or "슬라이드 설계 중")
        if (project / "design_spec.md").is_file():
            progress = max(progress, 45)
            stage = "슬라이드 설계 확정 중"
        image_manifest = project / "images" / "image_prompts.json"
        if image_manifest.is_file():
            try:
                image_items = json.loads(image_manifest.read_text(encoding="utf-8")).get("items") or []
            except (OSError, json.JSONDecodeError):
                image_items = []
            generated = sum(
                1 for item in image_items
                if (project / "images" / Path(str(item.get("filename", ""))).name).is_file()
            )
            if image_items:
                progress = max(progress, 48 + int(17 * generated / len(image_items)))
                stage = f"AI 이미지 생성 중 ({generated}/{len(image_items)})"
        svg_count = len(list((project / "svg_output").glob("*.svg")))
        if svg_count:
            total = max(1, slide_count)
            progress = max(progress, 66 + min(24, int(24 * svg_count / total)))
            stage = f"슬라이드 제작 중 ({min(svg_count, total)}/{total})"
        if list((project / "exports").glob("*.pptx")):
            progress = max(progress, 95)
            stage = "PowerPoint 최종 검사 중"
        self._write_status(
            job_id, log=(base + [accumulated])[-80:],
            progress=progress, stage=stage,
        )

    def _run(self, job_id: str, source: Path, options: dict):
        try:
            normalized = self._job_dir(job_id) / "normalized"
            self._write_status(job_id, status="running", stage="문서와 이미지 추출 중", progress=12)
            manifest = normalize_document(source, normalized)
            self._log(job_id, f"Markdown 변환 완료 · 이미지 {len(manifest['assets'])}개")

            if os.environ.get("KAIROS_PRESENTATION_FAKE") == "1":
                result = self._job_dir(job_id) / "result.pptx"
                result.write_bytes(b"PK\x03\x04fake-pptx")
                self._write_status(job_id, status="completed", stage="완료", progress=100,
                                   result=str(result), project_dir=str(normalized))
                return

            ppt_root = self._engine_dir("ppt-master")
            fleet_root = self._engine_dir("codex-fleet")
            prompt_kit = self._engine_dir("gongnyang-prompt-kit")
            if not ppt_root:
                raise RuntimeError("ppt-master를 찾을 수 없습니다")
            if options.get("use_ai_images", True) and not fleet_root:
                raise RuntimeError("codex-fleet를 찾을 수 없습니다")
            if options.get("use_ai_images", True) and not prompt_kit:
                raise RuntimeError("gongnyang-prompt-kit을 찾을 수 없습니다")

            pm_script = ppt_root / "skills" / "ppt-master" / "scripts" / "project_manager.py"
            base = self._job_dir(job_id) / "workspace"
            slug = "lecture"
            fmt = "ppt43" if options.get("aspect") == "4:3" else "ppt169"
            base.mkdir(parents=True, exist_ok=True)
            existing = sorted(
                (path for path in base.iterdir()
                 if path.is_dir() and (path / "sources").is_dir()),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if existing:
                project = existing[0]
                self._write_status(
                    job_id, stage="기존 PPT Master 프로젝트에서 재개 중", progress=25,
                )
            else:
                self._write_status(job_id, stage="PPT Master 프로젝트 준비 중", progress=25)
                try:
                    subprocess.run([sys.executable, str(pm_script), "init", slug,
                                    "--format", fmt, "--dir", str(base)],
                                   check=True, capture_output=True, timeout=180,
                                   stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace")
                except subprocess.CalledProcessError as exc:
                    detail = (exc.stderr or exc.stdout or "").strip()
                    raise RuntimeError(f"PPT Master 프로젝트 초기화 실패: {detail[-1200:]}") from exc
                except subprocess.TimeoutExpired as exc:
                    raise RuntimeError("PPT Master 프로젝트 초기화가 180초 안에 끝나지 않았습니다") from exc
                project = next(
                    path for path in base.iterdir()
                    if path.is_dir() and (path / "sources").is_dir()
                )
            shutil.copy2(normalized / "lecture.md", project / "sources" / "lecture.md")
            shutil.copy2(normalized / "assets.json", project / "sources" / "assets.json")
            if (normalized / "assets").is_dir():
                for asset in (normalized / "assets").iterdir():
                    shutil.copy2(asset, project / "images" / asset.name)

            helper = Path(__file__).resolve().parent / "presentation_fleet.py"
            # Kairos vendors the codex-fleet runner entrypoint so compatibility
            # fixes (for example Codex's current `call_*.png` output names) do
            # not depend on an external checkout being updated in lockstep.
            runner = Path(__file__).resolve().parent / "codex_imagegen_runner.py"
            if not runner.is_file():
                runner = (fleet_root / "runners" / "codex_imagegen_runner.py") if fleet_root else None
            provider_name = str(options.get("provider", "codex"))
            if provider_name not in {"codex", "claude"}:
                provider_name = "codex"
            cfg = {
                "workspace_dir": str(project),
                "codex_sandbox": "workspace-write",
                "claude_permission_mode": "acceptEdits",
                "claude_allowed_tools": [
                    f"Bash({sys.executable} {ppt_root / 'skills' / 'ppt-master' / 'scripts'}/*:*)",
                    f"Bash({sys.executable} {helper}:*)",
                ],
            }
            self._begin_stream_log(job_id)

            def run_agent(agent_prompt: str, stage: str, progress: int):
                self._write_status(
                    job_id, stage=stage, progress=progress, project_dir=str(project),
                )
                final = None
                for event in providers.get(provider_name).chat(agent_prompt, cfg=cfg):
                    if event["type"] in {"delta", "progress"}:
                        self._stream_log(
                            job_id, event.get("text", ""), project,
                            int(options.get("slide_count") or 10),
                        )
                    elif event["type"] == "error":
                        raise RuntimeError(event.get("error", "에이전트 실행 실패"))
                    elif event["type"] == "done":
                        final = event
                if not final:
                    raise RuntimeError("에이전트가 결과 없이 종료했습니다")

            def export_pptx():
                """Run PPT Master's exporter outside the nested Codex session."""
                exporter = (
                    ppt_root / "skills" / "ppt-master" / "scripts" / "svg_to_pptx.py"
                )
                if not exporter.is_file():
                    raise RuntimeError(f"PPTX exporter not found: {exporter}")
                export_result = subprocess.run(
                    [sys.executable, str(exporter), str(project)],
                    cwd=str(project),
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=300,
                )
                if export_result.returncode:
                    detail = (
                        export_result.stderr or export_result.stdout or ""
                    ).strip()
                    raise RuntimeError(f"PPTX export failed: {detail[-2400:]}")

            use_ai = bool(options.get("use_ai_images", True))
            if use_ai:
                if not runner or not runner.is_file() or not prompt_kit:
                    raise RuntimeError("AI 이미지 생성 실행 파일을 찾을 수 없습니다")
                selected_image_style = get_image_style(
                    str(options.get("image_style") or "")
                )
                image_style_lock = project / "images" / "image_style_lock.json"
                image_style_lock.write_text(
                    json.dumps(
                        {
                            "version": 1,
                            "image_style_id": selected_image_style["id"],
                            "name": selected_image_style["name"],
                            "visual_dna": selected_image_style["visual_dna"],
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                run_agent(
                    self._agent_prompt(
                        project, ppt_root, helper, runner, prompt_kit, options,
                        phase="plan",
                    ),
                    f"{provider_name}가 슬라이드와 이미지 설계 중",
                    40,
                )
                image_manifest = project / "images" / "image_prompts.json"
                if not image_manifest.is_file():
                    raise RuntimeError("이미지 설계 manifest가 생성되지 않았습니다")
                self._write_status(
                    job_id, stage="독립 워커가 AI 이미지 생성 중 (0/5)", progress=48,
                )
                fleet_result = subprocess.run(
                    [
                        sys.executable, str(helper),
                        "--manifest", str(image_manifest),
                        "--outdir", str(project / "images"),
                        "--runner", str(runner),
                        "--prompt-kit", str(prompt_kit),
                        "--style-lock", str(image_style_lock),
                    ],
                    cwd=str(project),
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=1500,
                )
                if fleet_result.returncode:
                    detail = (fleet_result.stderr or fleet_result.stdout or "").strip()
                    raise RuntimeError(f"AI 이미지 생성 실패: {detail[-2400:]}")
                image_payload = json.loads(image_manifest.read_text(encoding="utf-8"))
                image_items = image_payload.get("items") or []
                missing = [
                    Path(str(item.get("filename", ""))).name
                    for item in image_items
                    if item.get("status") != "Generated"
                    or not (project / "images" / Path(
                        str(item.get("filename", ""))
                    ).name).is_file()
                ]
                if not image_items or missing:
                    raise RuntimeError(
                        f"AI 이미지 결과가 불완전합니다: {', '.join(missing) or 'manifest 비어 있음'}"
                    )
                self._write_status(
                    job_id,
                    stage=f"AI 이미지 생성 완료 ({len(image_items)}/{len(image_items)})",
                    progress=65,
                )
                run_agent(
                    self._agent_prompt(
                        project, ppt_root, helper, runner, prompt_kit, options,
                        phase="execute",
                    ),
                    f"{provider_name}가 PowerPoint 제작 중",
                    66,
                )
                self._write_status(
                    job_id, stage="PPTX 내보내기 중", progress=94,
                )
                export_pptx()
            else:
                run_agent(
                    self._agent_prompt(
                        project, ppt_root, helper, runner, prompt_kit, options,
                    ),
                    f"{provider_name}가 슬라이드 설계 중",
                    40,
                )

            exports = sorted(project.glob("exports/*.pptx"),
                             key=lambda p: p.stat().st_mtime, reverse=True)
            if not exports:
                raise RuntimeError("PPT Master가 PPTX를 생성하지 못했습니다")
            result = self._job_dir(job_id) / f"{_safe_name(options.get('title') or source.stem)}.pptx"
            shutil.copy2(exports[0], result)
            self._write_status(job_id, status="completed", stage="완료", progress=100,
                               result=str(result))
        except Exception as exc:
            self._write_status(job_id, status="failed", stage="실패", error=str(exc))
        finally:
            self._stream_logs.pop(job_id, None)

    @staticmethod
    def _agent_prompt(project: Path, ppt_root: Path, helper: Path,
                      runner: Path | None, prompt_kit: Path | None,
                      options: dict, phase: str = "full") -> str:
        image_instruction = "원본 문서에서 추출된 이미지만 사용하세요."
        if options.get("use_ai_images", True) and runner and prompt_kit:
            target_assets = max(3, min(6, (int(options.get("slide_count") or 10) + 1) // 2))
            if phase == "execute":
                image_instruction = (
                    "독립 백그라운드 워커가 `images/image_prompts.json`의 모든 AI 이미지를 "
                    "이미 생성했고 각 항목을 `Generated`로 검증했습니다. manifest와 실제 PNG를 "
                    "읽어 계획된 슬라이드에 배치하세요. 이미지 프롬프트를 수정하거나 Fleet, "
                    "imagegen, image_gen.py를 다시 실행하지 마세요. 기존 `design_spec.md`와 "
                    "`spec_lock.md`를 이어받아 SVG 제작, 검증, 후처리, PPTX export를 완료하세요."
                )
            else:
                image_instruction = (
                "AI 시각 자산 생성은 사용자가 선택한 필수 제작 단계이며 생략할 수 없습니다. "
                f"이미지 목적과 배치가 확정되면 먼저 Prompt Kit `{prompt_kit / 'skills' / 'image-prompt' / 'SKILL.md'}`를 "
                "처음부터 끝까지 읽고, 라우팅 규칙에 따라 C12와 선택한 룩 프리셋 및 필요한 "
                "참조 문서를 읽으세요. 각 거친 이미지 의도를 Prompt Kit 포맷 A의 완성 프롬프트로 "
                "컴파일하고, 덱 전체에 동일한 DNA 블록을 적용하세요. 최종 prompt는 반드시 "
                "`AR 16:9`로 끝나야 합니다. "
                f"Strategist 단계에서 약 {target_assets}개의 핵심 시각 자산을 계획하세요. "
                "최소한 표지용 고품질 히어로 이미지와 강의의 핵심 개념을 설명하는 일관된 스타일의 "
                "삽화/장면 이미지를 포함하되, 단순 장식용 이미지를 모든 장에 반복하지 마세요. "
                "사용자가 별도로 플랫 스타일을 요구하지 않았다면 구체적인 장소·인물·사물을 "
                "주인공으로 삼고, 깊이 있는 조명·질감·원근을 결과 중심 문장으로 기술하세요. "
                "추상적인 원·선·도형 대신 실제 장면이 화면을 채우도록 긍정형으로 서술하세요. "
                "Prompt Kit tier 0 검증을 위해 영어 부정 표현 `no`, `without`, `avoid`, "
                "`exclude`, `never`, `free of`, `devoid of`, `do not`, `don't`를 prompt에 "
                "사용하지 말고, 원하는 시각 상태만 긍정형으로 표현하세요. "
                "이미지 안에는 글자를 넣지 말고 제목과 본문은 편집 가능한 SVG 텍스트로 유지하세요. "
                "맞춤형 스폿 아이콘이나 오브젝트가 꼭 필요하면 배경 분리가 쉬운 단색 배경의 독립 "
                "피사체로 생성하고, 일반 UI 아이콘은 PPT Master의 벡터 아이콘을 사용하세요. "
                "PPT Master 규칙대로 `design_spec.md`, `spec_lock.md`, "
                "`images/image_prompts.json`을 작성하고 manifest의 항목은 `Pending`으로 두세요. "
                "이 계획 단계에서는 Fleet, imagegen, image_gen.py를 실행하지 말고 SVG나 PPTX도 "
                "아직 만들지 마세요. 필요한 이미지와 배치 설계가 끝나면 최종 답변을 정확히 "
                "`KAIROS_IMAGE_PLAN_READY`로 마치세요. 이미지 생성은 독립 워커가 다음 단계에서 "
                "수행합니다."
                )
        if phase == "plan":
            route_instruction = (
                "이번 단계에서는 Generate PPTX의 Strategist/이미지 계획 단계까지만 수행하세요."
            )
            finish_instruction = (
                "SVG 검증이나 PPTX export는 수행하지 말고 이미지 계획 준비 완료를 알리세요."
            )
        elif phase == "execute":
            route_instruction = (
                "SVG 슬라이드, 발표자 노트, svg_final 산출물 생성과 검증까지만 수행하세요. "
                "svg_to_pptx.py를 실행하거나 PPTX를 만들지 마세요. PPTX 내보내기는 "
                "독립 카이로스 워커가 담당합니다."
            )
            finish_instruction = (
                "SVG 검증, 노트 분리, svg_final 생성까지 완료한 뒤 최종 답변을 정확히 "
                "`KAIROS_PPT_SOURCES_READY`로 마치세요."
            )
        else:
            route_instruction = (
                "Generate PPTX 경로를 끝까지 수행하여 exports/에 PPTX를 만드세요."
            )
            finish_instruction = (
                "모든 SVG 검증과 후처리, PPTX export까지 완료한 뒤 결과 경로를 최종 답변에 적으세요."
            )
        style_instruction = presentation_style_prompt(
            str(options.get("style_preset") or "")
        )
        selected_image_style = image_style_prompt(
            str(options.get("image_style") or "")
        )
        return f"""
아래 PPT Master 스킬을 사용해 강의안으로 편집 가능한 PowerPoint를 완성하세요.
스킬 진입점: {ppt_root / 'skills' / 'ppt-master' / 'SKILL.md'}
프로젝트: {project}
입력 본문: {project / 'sources' / 'lecture.md'}
추출 자산 목록: {project / 'sources' / 'assets.json'}

사용자가 카이로스 화면에서 아래 제작 사양을 직접 확정했고, 나머지 세부 디자인 판단을
에이전트에게 명시적으로 위임했습니다. 별도 확인 UI를 열거나 질문하지 마세요.
{route_instruction}
모든 Python 스크립트는 `{sys.executable}` 인터프리터로 실행하세요.
현재 운영체제는 Windows PowerShell입니다. Bash heredoc(`<<`, `<<'PY'`)과 셸 입력
리다이렉션으로 Python 코드를 실행하지 마세요. 여러 줄 Python이 필요하면 프로젝트 안에
`.py` 파일을 작성한 뒤 `{sys.executable} script.py` 형태로 실행하세요.
비대화형 작업이므로 live preview/Flask 서버나 브라우저를 시작하지 마세요.
- 제목: {options.get('title', '강의안')}
- 대상: {options.get('audience', '일반 학습자')}
- 슬라이드 수: 약 {options.get('slide_count', 10)}장
- 화면 비율: {options.get('aspect', '16:9')}
- 분위기: {options.get('tone', '명료하고 현대적인 교육 자료')}
- 저장된 디자인 시스템:
{style_instruction}
- AI 이미지 Visual DNA:
{selected_image_style}
- 외부 사실 조사: 하지 않음. 제공된 강의안만 사용
- 발표자 노트: {bool(options.get('speaker_notes', True))}

한글 원고가 주언어이면 구조적 제목·부제·본문은 설치된 `Noto Sans KR` 한 서체로
통일하고, 제목 700·본문 400/500처럼 굵기로 위계를 만드세요. 한글 구조 텍스트에
`Aptos`, `Aptos Display`, `Malgun Gothic`을 섞지 마세요. 제목과 부제는 각각 의도한
모듈 폭을 가진 별도 프레임으로 두고, 실제 한글 글자 폭을 기준으로 줄바꿈한 뒤 최소
16px의 시각 간격을 확보하세요. 본문 프레임은 컨테이너 안쪽 여백과 예상 줄 수를
반영한 폭·높이를 가져야 하며 글자가 카드 밖으로 잘리면 안 됩니다.
FLOW·단계·수렴 다이어그램은 항목 중심점, 동일 간격, 연결선 시작/끝점, 결과 박스의
수직 중심을 수치로 맞추고, 모든 라벨과 설명이 각 도형 안에서 완전히 보여야 합니다.
숫자 원·배지는 숫자 글리프의 시각 중심을 원 중심에 맞추세요. SVG 텍스트 기준선은
`y = circle cy + 약 0.32 × font-size`를 출발점으로 실제 렌더를 확인하고, 원과 숫자가
따로 떠 보이는 기준선 배치를 금지합니다. 카드 제목은 숫자 배지와 안쪽 여백을 뺀
실제 가용 폭으로 측정하며, 넘치면 글자 크기를 과도하게 줄이지 말고 의미 단위로
수동 줄바꿈하고 카드 높이와 아래 본문 위치를 함께 조정하세요.
SVG 캔버스 검사 통과만으로 완료하지 말고 PowerPoint 변환 후 텍스트 재배치까지
고려해 넉넉한 프레임을 설계하세요.

원본 이미지는 의미와 출처를 유지해 우선 활용하되, 생성 이미지와 함께 쓰일 때는 동일한
크롭 비율·모서리·여백·캡션·색상 오버레이 체계로 프레이밍해 한 덱의 시각 언어로
보이게 하세요. 표는 가능하면 편집 가능한 표로 만드세요.
{image_instruction}
{finish_instruction}
""".strip()
