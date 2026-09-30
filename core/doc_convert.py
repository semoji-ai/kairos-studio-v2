"""문서 → 마크다운 텍스트 변환. PPT 제작과 원고 학습이 함께 쓴다."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

SUPPORTED_EXTS = {".pdf", ".docx", ".hwp", ".hwpx", ".md", ".markdown", ".txt"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff",
               ".webp", ".svg", ".emf", ".wmf"}

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


def _read_plain(source: Path) -> str:
    data = source.read_bytes()
    for enc in ("utf-8-sig", "cp949"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def extract_text(source: Path, work_dir: Path) -> tuple[str, list[dict]]:
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_EXTS:
        raise ValueError(f"지원하지 않는 파일 형식입니다: {suffix}")
    work_dir.mkdir(parents=True, exist_ok=True)
    if suffix in {".md", ".markdown", ".txt"}:
        return _read_plain(source), []
    if suffix == ".docx":
        return _extract_docx(source, work_dir)
    if suffix == ".hwpx":
        return _extract_hwpx(source, work_dir)
    if suffix == ".hwp":
        converted = work_dir / (source.stem + ".hwpx")
        if _convert_hwp_to_hwpx(source, converted):
            return _extract_hwpx(converted, work_dir)
        txt = converted.with_suffix(".txt")
        if txt.is_file():
            return txt.read_text(encoding="utf-8"), []
        raise RuntimeError("HWP 변환 실패: 한컴오피스 또는 hwp5txt가 필요합니다")
    return _extract_pdf(source, work_dir)
