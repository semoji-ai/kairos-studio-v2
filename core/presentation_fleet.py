"""PPT Master image manifest -> codex-fleet adapter.

PPT Master owns image selection and prompt authoring.  This module only maps
its audited JSON manifest to codex-fleet's JSONL contract, runs the fleet
runner, and reflects output status back into the original manifest.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def _passes_quality_gate(path: Path) -> bool:
    """Reject empty/placeholder-like assets before PPT Master can consume them."""
    if not path.is_file() or path.stat().st_size < 250_000:
        return False
    try:
        from PIL import Image
        with Image.open(path) as image:
            width, height = image.size
            return min(width, height) >= 900
    except (ImportError, OSError):
        return False


def _size_for(item: dict) -> str:
    ratio = str(item.get("aspect_ratio", "16:9")).strip()
    quality = str(item.get("image_size", "2K")).upper()
    if quality == "4K":
        return "2048x2048"
    if ratio in {"16:9", "16/9", "1.777"}:
        return "1792x1024"
    if ratio in {"9:16", "9/16", "0.5625"}:
        return "1024x1792"
    if ratio in {"2:3", "2/3"}:
        return "1024x1536"
    if ratio in {"3:2", "3/2"}:
        return "1536x1024"
    if ratio in {"4:3", "4/3"}:
        return "1536x1024"
    if ratio in {"3:4", "3/4"}:
        return "1024x1536"
    return "1024x1024"


def _normalized_prompt(item: dict) -> str:
    prompt = str(item.get("prompt", "")).strip()
    # PPT authors commonly express Prompt Kit Format A as numbered Markdown
    # headings. The validator recognizes colon labels, so canonicalize the
    # equivalent heading notation before validation and generation.
    prompt = re.sub(
        r"(?im)^#{1,6}\s*\d+\.\s*"
        r"(Scene|Camera|Lighting|Color grading|Texture/Medium|Text-in-image|Visual policy)"
        r"\s*$",
        lambda match: f"{match.group(1)}:",
        prompt,
    )
    if str(item.get("text_policy", "")).strip().lower() in {
        "none", "no-text", "no_text", "editable_svg_only", "svg_only",
    }:
        # Prompt Kit treats the literal section label `Text-in-image:` as a
        # request to render copy, even when the sentence explicitly says that
        # the frame contains no lettering. Preserve the visual instruction
        # while making its intent unambiguous to both the validator and model.
        prompt = re.sub(
            r"(?i)\btext-in-image\s*:",
            "Visual policy:",
            prompt,
        )
        prompt = re.sub(
            r"(?i)\b(?:free of|devoid of|without|no)\s+"
            r"(?:rendered\s+)?(?:lettering|text|words|labels|logos?)\b",
            "with clean unmarked surfaces",
            prompt,
        )
    # Frequent natural-language phrases produced for documentary scenes are
    # visually valid but violate Prompt Kit's positive-only Tier-0 grammar.
    prompt = re.sub(
        r"(?i)\bwithout staged sentiment\b",
        "with natural, unstaged documentary emotion",
        prompt,
    )
    prompt = re.sub(
        r"(?i)\bwithout symbols competing for attention\b",
        "with restrained symbolism and a clear visual hierarchy",
        prompt,
    )
    return prompt


def apply_image_style_lock(payload: dict, style_lock: dict) -> dict:
    """Deterministically stamp one immutable visual DNA onto every image."""
    style_id = str(style_lock.get("image_style_id") or "").strip()
    visual_dna = str(style_lock.get("visual_dna") or "").strip()
    if not style_id or not visual_dna:
        raise RuntimeError("AI 이미지 스타일 잠금 파일이 올바르지 않습니다")
    payload["image_style_id"] = style_id
    payload["visual_dna"] = visual_dna
    for item in payload.get("items") or []:
        prompt = str(item.get("prompt") or "").strip()
        prompt = re.sub(r"\s*AR\s+\d+\s*:\s*\d+\s*$", "", prompt,
                        flags=re.IGNORECASE).strip()
        marker = f"Visual DNA: {visual_dna}"
        if marker not in prompt:
            prompt = f"{prompt}\n{marker}".strip()
        item["image_style_id"] = style_id
        item["visual_dna"] = visual_dna
        item["prompt"] = f"{prompt}\nAR {item.get('aspect_ratio', '16:9')}"
    return payload


def validate_image_style_lock(payload: dict, style_lock: dict) -> None:
    style_id = str(style_lock.get("image_style_id") or "")
    visual_dna = str(style_lock.get("visual_dna") or "")
    if payload.get("image_style_id") != style_id or payload.get("visual_dna") != visual_dna:
        raise RuntimeError("이미지 manifest의 Visual DNA 잠금이 일치하지 않습니다")
    for index, item in enumerate(payload.get("items") or [], 1):
        if (
            item.get("image_style_id") != style_id
            or item.get("visual_dna") != visual_dna
            or f"Visual DNA: {visual_dna}" not in str(item.get("prompt") or "")
        ):
            raise RuntimeError(f"이미지 {index}의 Visual DNA가 작업 스타일과 다릅니다")


def convert_manifest(manifest: Path, jsonl_path: Path) -> tuple[dict, list[dict]]:
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    items = []
    for index, item in enumerate(payload.get("items") or [], 1):
        filename = Path(str(item.get("filename", ""))).name
        prompt = _normalized_prompt(item)
        if not filename or not prompt:
            continue
        item["prompt"] = prompt
        items.append({
            "id": f"ppt-{index:03d}",
            "prompt": prompt,
            "ar": str(item.get("aspect_ratio", "16:9")),
            "size": _size_for(item),
            "output_path": filename,
        })
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    jsonl_path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in items),
        encoding="utf-8",
    )
    return payload, items


def validate_prompts(payload: dict, prompt_kit: Path) -> None:
    validator = prompt_kit / "skills" / "image-prompt" / "scripts" / "check_prompt.mjs"
    if not validator.is_file():
        raise RuntimeError(f"Prompt Kit 검증기를 찾을 수 없습니다: {validator}")
    validator_arg = str(validator)
    if os.name == "nt" and validator_arg.startswith("\\\\?\\"):
        # Node treats Win32 extended-length paths as URL-like input in this
        # invocation and can collapse `\\?\D:\...` to the directory `D:`.
        validator_arg = validator_arg[4:]
    for index, item in enumerate(payload.get("items") or [], 1):
        prompt = _normalized_prompt(item)
        item["prompt"] = prompt
        if not prompt:
            raise RuntimeError(f"이미지 프롬프트 {index}가 비어 있습니다")
        result = subprocess.run(
            ["node", validator_arg, "--tier", "0"],
            input=prompt,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=30,
        )
        try:
            report = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Prompt Kit 검증 결과를 읽을 수 없습니다: {(result.stderr or result.stdout)[-800:]}"
            ) from exc
        if result.returncode != 0 or not report.get("ok"):
            errors = "; ".join(
                f"{entry.get('code')}: {entry.get('msg')}"
                for entry in report.get("errors") or []
            )
            raise RuntimeError(f"이미지 프롬프트 {index} 검증 실패: {errors}")


def run_fleet(manifest: Path, outdir: Path, runner: Path,
              prompt_kit: Path, parallel: str = "auto", timeout: int = 240,
              style_lock: Path | None = None) -> int:
    work = manifest.parent / ".kairos-fleet"
    jsonl_path = work / "manifest.jsonl"
    if style_lock:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        lock_payload = json.loads(style_lock.read_text(encoding="utf-8"))
        apply_image_style_lock(payload, lock_payload)
        validate_image_style_lock(payload, lock_payload)
        manifest.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    payload, items = convert_manifest(manifest, jsonl_path)
    validate_prompts(payload, prompt_kit)
    outdir.mkdir(parents=True, exist_ok=True)

    if not items:
        return 0

    env = os.environ.copy()
    env.update({
        "PROMPTS": str(jsonl_path),
        "OUTDIR": str(outdir),
        "PARALLEL": parallel,
        # Codex CLI initialization touches shared per-user state on Windows.
        # Start conservatively, then let the fleet scaler grow after healthy
        # completions while retaining its target/hard cap (up to 32).
        "START": str(min(len(items), 2)),
        "RAMP_EVERY": "1",
        "LAUNCH_STAGGER": "2",
        "TIMEOUT": str(timeout),
    })
    result = subprocess.run(
        [sys.executable, str(runner)],
        cwd=str(runner.parent),
        env=env,
        stdin=subprocess.DEVNULL,
        timeout=max(timeout * len(items), timeout + 60),
    )

    by_name = {Path(str(item.get("filename", ""))).name: item
               for item in payload.get("items") or []}
    for name, item in by_name.items():
        item["status"] = "Generated" if _passes_quality_gate(outdir / name) else "Failed"
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return result.returncode or (1 if any(
        item.get("status") == "Failed" for item in by_name.values()) else 0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--outdir", required=True, type=Path)
    parser.add_argument("--runner", required=True, type=Path)
    parser.add_argument("--prompt-kit", required=True, type=Path)
    parser.add_argument("--style-lock", type=Path)
    parser.add_argument("--parallel", default="auto")
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args(argv)
    return run_fleet(args.manifest, args.outdir, args.runner, args.prompt_kit,
                     parallel=args.parallel, timeout=args.timeout,
                     style_lock=args.style_lock)


if __name__ == "__main__":
    raise SystemExit(main())
