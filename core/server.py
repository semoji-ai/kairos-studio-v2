"""HTTP+SSE 서버. stdlib http.server 기반 (기존 kairos-studio 패턴 이식)."""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import threading
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from core import bible_coverage, documents, providers, sermon_rag, settings, setup
from core.artifacts import collect
from core.distill import distill
from core.document_versions import resolve_editable, save_version
from core.output_workspace import instruction as output_instruction
from core.output_workspace import mirror_outputs, session_dir as output_session_dir
from core.presentations import PresentationManager
from core.recall import recall
from core.router import route
from core.store import Store

_INJECT_BUDGET = 1500
_MAX_REVIEW_BYTES = 1 * 1024 * 1024
DISTILL_THRESHOLD = 10
_distill_lock = threading.Lock()


def _is_routine_disconnect(error: BaseException | None) -> bool:
    return isinstance(
        error,
        (ConnectionResetError, ConnectionAbortedError, BrokenPipeError),
    )


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    """Ignore expected browser disconnects without hiding real server faults."""

    def handle_error(self, request, client_address):
        if _is_routine_disconnect(sys.exc_info()[1]):
            return
        super().handle_error(request, client_address)


def _open_local_path(path: Path, reveal: bool = False) -> None:
    """Open a generated local file or reveal it in the platform file manager."""
    if os.name == "nt":
        if reveal:
            subprocess.Popen(["explorer.exe", "/select,", str(path)])
        else:
            os.startfile(str(path))
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)] if reveal else ["open", str(path)])
        return
    subprocess.Popen(["xdg-open", str(path.parent if reveal else path)])


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _annotate_sermon_history(refs: list[dict], workspace_dir: str | None) -> None:
    """검색된 구절에 목사님의 설교 이력을 주석으로 붙인다 (순위는 건드리지 않음).

    카이로스를 늦게 설치한 목사님은 축적 대부분이 publish_agent 워크스페이스에
    있고 kairos.db 피드백은 비어 있다. 이 라벨은 그 공백을 정보로 메운다 —
    이미 다룬 본문인지 아닌지는 사람이 판단할 몫이라 순위는 그대로 둔다.
    """
    if not refs or not workspace_dir:
        return
    try:
        history = bible_coverage.sermon_history(workspace_dir)
    except Exception:
        return
    if not history:
        return
    for ref in refs:
        key = documents.ref_key(ref.get("reference", ""))
        entry = history.get(key) if key else None
        if not entry:
            continue
        note = f"목사님 설교 {entry['count']}회"
        if entry.get("last_date"):
            note += f"·최근 {entry['last_date']}"
        ref["sermon_note"] = note


def build_prompt(text: str, rec: dict) -> tuple[str, int]:
    """스펙 ③ 형식으로 회상 결과를 원문 앞에 조립.

    반환: (프롬프트, 주입된 스니펫 수). 회상 결과가 전부 비어 있으면 (text, 0).
    부수효과로 rec["bible_refs_used"]에 실제로 블록에 살아남은 성경 자료를
    남긴다 — 예산 때문에 잘린 구절까지 학습 신호로 귀속되면 안 되기 때문.
    1,500자 하드캡 초과 시 스니펫을 뒤에서부터 제거해 캡 이하로 맞춘다
    (corrections/avoid는 우선 보존). 캡은 주입 블록의 길이만 측정하며,
    사용자 텍스트의 길이는 무시한다.
    """
    snippets = list(rec.get("snippets") or [])
    avoid = list(rec.get("avoid") or [])
    corrections = list(rec.get("corrections") or [])
    rules = list(rec.get("rules") or [])
    bible_refs = list(rec.get("bible_refs") or [])
    document_edits = list(rec.get("document_edits") or [])

    def render_block(snips: list[dict], rls: list[str], refs: list[dict],
                     edits: list[dict]) -> str:
        blocks = []
        if rls:
            lines = "\n".join(f"- {r}" for r in rls)
            blocks.append(f"[학습된 규칙 — 항상 준수]\n{lines}")
        if refs:
            # 원전분해 등 대용량 항목이 프롬프트를 오염시키지 않게 항목당 길이 제한
            lines = "\n".join(
                f"[{r.get('reference', '')}] {str(r.get('content', ''))[:180]}"
                + (f" ({r['sermon_note']})" if r.get("sermon_note") else "")
                for r in refs[:3]
            )
            blocks.append(f"[성경 자료 검색 — 관련 구절]\n{lines}")
        if snips:
            lines = "\n".join(
                f"({s.get('date', '')}) Q: {s.get('q_text', '')} A: {s.get('a_text', '')}"
                for s in snips
            )
            blocks.append(f"[과거 대화 참고 — 관련 있을 때만 활용]\n{lines}")
        if corrections:
            lines = "\n".join(f"- {c}" for c in corrections)
            blocks.append(f"[사용자 교정 이력 — 반드시 준수]\n{lines}")
        if avoid:
            lines = "\n".join(f"- {a}" for a in avoid)
            blocks.append(f"[회피 신호 — 이런 식의 답변은 거부된 적 있음]\n{lines}")
        if edits:
            lines = "\n\n".join(
                f"문서: {Path(e.get('path', '')).name}\n"
                f"{str(e.get('diff', ''))[:500]}"
                for e in edits[:3]
            )
            blocks.append(
                "[목사님 문서 수정 학습 — AI 원문보다 수정 후 표현을 우선]\n"
                f"{lines}"
            )
        if not blocks:
            return ""
        return "\n\n".join(blocks)

    block = render_block(snippets, rules, bible_refs, document_edits)
    while block and len(block) > _INJECT_BUDGET and snippets:
        snippets = snippets[:-1]
        block = render_block(snippets, rules, bible_refs, document_edits)
    # 스니펫을 다 줄여도 여전히 캡 초과면 규칙을 오래된 것부터(리스트 끝) 줄인다.
    # store.list_rules()는 id 내림차순(최신 우선)이므로 끝을 자르면 최신이 남는다.
    while block and len(block) > _INJECT_BUDGET and rules:
        rules = rules[:-1]
        block = render_block(snippets, rules, bible_refs, document_edits)
    # 마지막으로 성경 자료도 필요시 줄인다.
    while block and len(block) > _INJECT_BUDGET and bible_refs:
        bible_refs = bible_refs[:-1]
        block = render_block(snippets, rules, bible_refs, document_edits)
    while block and len(block) > _INJECT_BUDGET and document_edits:
        document_edits = document_edits[:-1]
        block = render_block(snippets, rules, bible_refs, document_edits)

    if not block:
        rec["bible_refs_used"] = []
        return text, 0
    # render_block이 refs[:3]만 그리므로 기록도 같은 범위로 맞춘다.
    rec["bible_refs_used"] = bible_refs[:3]
    prompt = block + "\n\n---\n" + text
    return prompt, len(snippets)


def _last_session_ref(store: Store, session_id: int, provider: str) -> str | None:
    """같은 provider의 직전 assistant 메시지에서 session_ref를 찾는다."""
    for m in reversed(store.list_messages(session_id)):
        if m["role"] == "assistant" and m["provider"] == provider:
            for part in m["content"]:
                if part.get("type") == "meta" and part.get("session_ref"):
                    return part["session_ref"]
            return None
    return None


_CLI_LOGIN_HINT = {"claude": "claude /login", "codex": "codex login"}


def _resolve_cmd(name: str) -> list[str] | None:
    """providers.claude/codex의 _base_cmd와 동일 규칙: env 오버라이드 우선."""
    env_key = f"KAIROS_{name.upper()}_CMD"
    override = os.environ.get(env_key)
    if override:
        return override.split()
    exe = shutil.which(name)
    return [exe] if exe else None


def _cli_version(cmd: list[str]) -> str | None:
    try:
        r = subprocess.run(cmd + ["--version"], capture_output=True,
                            timeout=10, encoding="utf-8", errors="replace")
    except Exception:
        return None
    out = (r.stdout or r.stderr or "").strip()
    return out.splitlines()[0] if out else None


def _cli_authed(name: str, cmd: list[str]) -> bool | None:
    # 실측(2026-07): `claude auth status` returncode==0(로그인 시), `codex login
    # status` returncode==0(로그인 시) — 둘 다 신뢰 가능한 서브커맨드.
    try:
        if name == "codex":
            r = subprocess.run(cmd + ["login", "status"], capture_output=True,
                                timeout=10, encoding="utf-8", errors="replace")
        else:
            r = subprocess.run(cmd + ["auth", "status"], capture_output=True,
                                timeout=10, encoding="utf-8", errors="replace")
        return r.returncode == 0
    except Exception:
        return None


def _cli_status_one(name: str) -> dict:
    cmd = _resolve_cmd(name)
    installed = cmd is not None
    version = _cli_version(cmd) if installed else None
    authed = _cli_authed(name, cmd) if installed else None
    return {"installed": installed, "version": version, "authed": authed,
            "login_hint": _CLI_LOGIN_HINT[name]}


def _workspace_info_dict(ws_str: str | None) -> dict:
    """workspace/info와 setup/status가 공유하는 스킬 감지 로직."""
    if ws_str is None:
        return {"workspace_dir": None, "exists": None, "skills": [], "has_claude_md": False}
    ws = Path(ws_str).expanduser()
    exists = ws.is_dir()
    skills: set[str] = set()
    if exists:
        claude_skills = ws / ".claude" / "skills"
        if claude_skills.is_dir():
            for d in claude_skills.iterdir():
                if d.is_dir():
                    skills.add(d.name)
        plain_skills = ws / "skills"
        if plain_skills.is_dir():
            for d in plain_skills.iterdir():
                if d.is_dir() and (d / "SKILL.md").is_file():
                    skills.add(d.name)
    has_claude_md = exists and (ws / "CLAUDE.md").is_file()
    return {"workspace_dir": ws_str, "exists": exists, "skills": sorted(skills),
            "has_claude_md": has_claude_md}


def make_server(host: str, port: int, token: str, store: Store) -> ThreadingHTTPServer:
    state = {"store": store}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def _send(self, code: int, payload: dict):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _host_ok(self) -> bool:
            host = self.headers.get("Host", "")
            host = host.rsplit(":", 1)[0] if ":" in host else host
            return host in ("127.0.0.1", "localhost")

        def _authed(self) -> bool:
            hdr = self.headers.get("Authorization", "")
            if not hdr.startswith("Bearer "):
                return False
            try:
                return secrets.compare_digest(
                    hdr[7:].encode("utf-8", "surrogatepass"), token.encode("utf-8"))
            except (ValueError, TypeError):
                return False

        def _body(self) -> dict | None:
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
            except ValueError:
                return None
            raw = self.rfile.read(length) if length else b"{}"
            try:
                return json.loads(raw.decode("utf-8")) if raw.strip() else {}
            except (UnicodeDecodeError, json.JSONDecodeError):
                return None

        def _multipart(self) -> tuple[str, bytes, dict] | None:
            """Parse one uploaded file plus UTF-8 form fields."""
            ctype = self.headers.get("Content-Type", "")
            if not ctype.lower().startswith("multipart/form-data"):
                return None
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return None
            if length <= 0 or length > 135 * 1024 * 1024:
                return None
            raw = self.rfile.read(length)
            message = BytesParser(policy=policy.default).parsebytes(
                f"Content-Type: {ctype}\r\nMIME-Version: 1.0\r\n\r\n".encode() + raw)
            filename = ""
            content = b""
            fields: dict[str, object] = {}
            for part in message.iter_parts():
                name = part.get_param("name", header="content-disposition")
                part_filename = part.get_filename()
                payload = part.get_payload(decode=True) or b""
                if part_filename is not None and name == "file":
                    filename = part_filename
                    content = payload
                elif name:
                    value = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                    if value.lower() in {"true", "false"}:
                        fields[name] = value.lower() == "true"
                    elif name == "slide_count":
                        try:
                            fields[name] = int(value)
                        except ValueError:
                            fields[name] = value
                    else:
                        fields[name] = value
            return (filename, content, fields) if filename else None

        # ---- SSE ----
        def _sse_start(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()

        def _sse(self, obj: dict):
            data = json.dumps(obj, ensure_ascii=False)
            self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
            self.wfile.flush()

        # ---- routes ----
        def do_GET(self):
            if not self._host_ok():
                return self._send(403, {"error": "forbidden host"})
            u = urlparse(self.path)
            if u.path == "/health":
                return self._send(200, {"ok": True})
            # 인증은 API 라우트에만. 그 외 경로는 Task 8에서 정적 서빙이 된다
            # (토큰이 index.html 주입으로 전달되므로 정적은 인증 불가/불요).
            api_path = (
                u.path in ("/sessions", "/messages", "/settings", "/storage", "/cli/status",
                           "/workspace/info", "/rules", "/setup/status", "/bible/coverage",
                           "/presentations", "/presentations/engines", "/reviews")
                or u.path.startswith("/presentations/")
            )
            presentation_download = bool(
                re.fullmatch(r"/presentations/[0-9a-f]{12}/download", u.path)
            )
            download_token = parse_qs(u.query).get("token", [""])[0]
            download_token_ok = presentation_download and secrets.compare_digest(
                download_token, token
            )
            if api_path:
                if not download_token_ok and not self._authed():
                    return self._send(401, {"error": "unauthorized"})
                if u.path == "/presentations":
                    return self._send(200, {"jobs": self._presentation_manager().list()})
                if u.path == "/presentations/engines":
                    return self._send(200, self._presentation_manager().engines())
                if u.path.startswith("/presentations/"):
                    bits = u.path.strip("/").split("/")
                    if len(bits) == 2:
                        job = self._presentation_manager().get(bits[1])
                        return self._send(200, job) if job else self._send(404, {"error": "not found"})
                    if len(bits) == 3 and bits[2] == "download":
                        return self._serve_presentation(bits[1])
                if u.path == "/bible/coverage":
                    ws = settings.load().get("workspace_dir")
                    if not ws:
                        return self._send(200, {"books": [], "error": "workspace not set"})
                    try:
                        return self._send(200, bible_coverage.coverage(ws))
                    except Exception as exc:
                        return self._send(500, {"error": f"coverage failed: {exc}"})
                if u.path == "/rules":
                    store = state["store"]
                    return self._send(200, {"rules": store.list_rules(active_only=False),
                                             "undistilled": store.count_undistilled_feedback()})
                if u.path == "/reviews":
                    return self._list_reviews()
                if u.path == "/sessions":
                    return self._send(200, {"sessions": state["store"].list_sessions()})
                if u.path == "/messages":
                    q = parse_qs(u.query)
                    try:
                        sid = int(q.get("session_id", [""])[0])
                    except ValueError:
                        return self._send(400, {"error": "bad session_id"})
                    return self._send(200, {"messages": state["store"].list_messages(sid)})
                if u.path == "/settings":
                    return self._send(200, settings.load())
                if u.path == "/storage":
                    return self._storage()
                if u.path == "/cli/status":
                    return self._send(200, {"claude": _cli_status_one("claude"),
                                             "codex": _cli_status_one("codex")})
                if u.path == "/workspace/info":
                    return self._workspace_info()
                if u.path == "/setup/status":
                    return self._setup_status()
            # 아티팩트 서빙: 정적 서빙과 동일 근거로 Host 검증만(Bearer 불요 —
            # <img src="/artifacts/...">는 Authorization 헤더를 실을 수 없다).
            # 경로는 data_dir/artifacts 루트에 감금(resolve+relative_to).
            if u.path.startswith("/artifacts/"):
                return self._serve_artifact(u.path)
            if u.path == "/workspace-file":
                return self._serve_workspace_file(u.query)
            return self._serve_static()

        def _data_dir(self) -> Path:
            db_path = getattr(state["store"], "_path", None)
            if db_path is None:
                db_path = Path(settings.load()["data_dir"]).expanduser() / "kairos.db"
            return Path(db_path).parent

        def _presentation_manager(self) -> PresentationManager:
            bundle = os.environ.get("KAIROS_BUNDLE_DIR")
            return PresentationManager(self._data_dir(), Path(bundle) if bundle else None)

        def _serve_presentation(self, job_id: str):
            target = self._presentation_target(job_id)
            if target is None:
                return self._send(404, {"error": "result not found"})
            data = target.read_bytes()
            safe_title = re.sub(r"[^0-9A-Za-z가-힣._-]+", "-", target.name)
            self.send_response(200)
            self.send_header("Content-Type",
                             "application/vnd.openxmlformats-officedocument.presentationml.presentation")
            self.send_header("Content-Disposition",
                             f"attachment; filename*=UTF-8''{quote(safe_title)}")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _presentation_target(self, job_id: str) -> Path | None:
            job = self._presentation_manager().get(job_id)
            if not job or job.get("status") != "completed" or not job.get("result"):
                return None
            target = Path(job["result"])
            root = (self._data_dir() / "presentations" / job_id).resolve()
            try:
                target = target.resolve()
                target.relative_to(root)
            except (OSError, ValueError):
                return None
            if not target.is_file():
                return None
            return target

        def _open_presentation(self, job_id: str, reveal: bool):
            target = self._presentation_target(job_id)
            if target is None:
                return self._send(404, {"error": "result not found"})
            try:
                _open_local_path(target, reveal=reveal)
            except OSError as exc:
                return self._send(500, {"error": f"open failed: {exc}"})
            return self._send(200, {"ok": True, "path": str(target)})

        _ARTIFACT_CTYPES = {".png": "image/png", ".jpg": "image/jpeg",
                             ".jpeg": "image/jpeg", ".webp": "image/webp",
                             ".gif": "image/gif", ".md": "text/markdown",
                             ".json": "application/json"}

        def _serve_artifact(self, url_path: str):
            root = (self._data_dir() / "artifacts").resolve()
            rel = url_path[len("/artifacts/"):].split("?", 1)[0]
            target = (root / rel).resolve()
            try:
                target.relative_to(root)
            except ValueError:
                return self._send(404, {"error": "not found"})
            if not target.is_file():
                return self._send(404, {"error": "not found"})
            data = target.read_bytes()
            ctype = self._ARTIFACT_CTYPES.get(target.suffix.lower(), "application/octet-stream")
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _serve_workspace_file(self, query: str):
            q = parse_qs(query)
            request_token = q.get("token", [""])[0]
            if not secrets.compare_digest(request_token, token):
                return self._send(401, {"error": "unauthorized"})
            loaded_settings = settings.load()
            workspace = loaded_settings.get("workspace_dir")
            output_dir = loaded_settings.get("output_dir")
            raw_path = unquote(q.get("path", [""])[0])
            if not raw_path:
                return self._send(404, {"error": "not found"})
            try:
                candidate = Path(raw_path).expanduser()
                roots = [
                    Path(value).expanduser().resolve()
                    for value in (workspace, output_dir) if value
                ]
                if not roots:
                    return self._send(404, {"error": "not found"})
                target = candidate.resolve() if candidate.is_absolute() else (roots[0] / candidate).resolve()
                if not any(_is_relative_to(target, root) for root in roots):
                    return self._send(404, {"error": "not found"})
            except (OSError, ValueError):
                return self._send(404, {"error": "not found"})
            ctype = self._ARTIFACT_CTYPES.get(target.suffix.lower())
            if ctype is None or not target.is_file():
                return self._send(404, {"error": "not found"})
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _list_reviews(self):
            output = settings.load().get("output_dir")
            if not output:
                return self._send(200, {"reviews": []})
            try:
                root = Path(output).expanduser().resolve()
            except (OSError, ValueError):
                return self._send(200, {"reviews": []})
            if not root.is_dir():
                return self._send(200, {"reviews": []})
            reviews = []
            try:
                candidates = sorted(
                    root.rglob("*.review.json"),
                    key=lambda path: path.stat().st_mtime,
                    reverse=True,
                )
                for candidate in candidates[:100]:
                    target = candidate.resolve()
                    if not _is_relative_to(target, root) or target.stat().st_size > _MAX_REVIEW_BYTES:
                        continue
                    try:
                        payload = json.loads(target.read_text(encoding="utf-8"))
                    except (OSError, UnicodeError, json.JSONDecodeError):
                        continue
                    if payload.get("schema") != "kairos.theology-review.v1":
                        continue
                    claims = payload.get("claims")
                    if not isinstance(claims, list):
                        continue
                    decided = sum(
                        1 for claim in claims
                        if isinstance(claim, dict) and claim.get("status") != "pending"
                    )
                    reviews.append({
                        "path": str(target),
                        "title": str(payload.get("title") or target.stem),
                        "status": str(payload.get("review_status") or "in_review"),
                        "total": len(claims),
                        "decided": decided,
                        "updated_at": payload.get("updated_at"),
                    })
            except OSError:
                return self._send(200, {"reviews": []})
            return self._send(200, {"reviews": reviews})

        def _save_workspace_file(self, body: dict):
            cfg = settings.load()
            roots = [
                Path(value).expanduser()
                for value in (cfg.get("workspace_dir"), cfg.get("output_dir")) if value
            ]
            path_text = body.get("path")
            content = body.get("content")
            message_id = body.get("message_id")
            if not isinstance(path_text, str) or not isinstance(content, str):
                return self._send(400, {"error": "path and content are required"})
            try:
                target = resolve_editable(unquote(path_text), roots)
                result = save_version(target, content)
            except (OSError, UnicodeError, ValueError) as exc:
                return self._send(400, {"error": str(exc)})
            if result["changed"]:
                mid = int(message_id) if isinstance(message_id, int) else None
                state["store"].add_document_revision(mid, result)
                if mid is not None and state["store"].session_for_message(mid):
                    payload = (
                        "문서 편집에서 확인된 목사님 표현 수정:\n"
                        f"{result['diff'][:4000]}"
                    )
                    state["store"].add_feedback(mid, "correction", payload)
                    session = state["store"].session_for_message(mid)
                    try:
                        target_dir = output_session_dir(
                            cfg.get("output_dir"), session["id"], session["title"])
                        mirror_outputs(str(target), cfg.get("workspace_dir"), target_dir)
                        if target_dir is not None and result["version_path"]:
                            version_source = Path(result["version_path"])
                            version_target = (
                                target_dir / ".kairos-versions" / target.stem
                                / version_source.name
                            )
                            version_target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(version_source, version_target)
                    except OSError:
                        pass
            promoted = None
            if target.name.endswith(".review.json"):
                try:
                    promoted = sermon_rag.promote_approved_reviews(
                        cfg.get("workspace_dir"), cfg.get("output_dir")
                    )
                except (OSError, UnicodeError, ValueError):
                    promoted = None
            return self._send(200, {
                "changed": result["changed"],
                "path": result["path"],
                "version_path": result["version_path"],
                "additions": result["additions"],
                "deletions": result["deletions"],
                "learned": bool(result["changed"]),
                "promoted": promoted,
            })

        def _workspace_info(self):
            ws_str = settings.load()["workspace_dir"]
            return self._send(200, _workspace_info_dict(ws_str))

        def _setup_status(self):
            cli = {"claude": _cli_status_one("claude"), "codex": _cli_status_one("codex")}
            ws_str = settings.load()["workspace_dir"]
            ws_info = _workspace_info_dict(ws_str)
            workspace_ready = bool(ws_info["skills"])
            all_ready = bool(cli["claude"]["installed"]) and bool(cli["claude"]["authed"])
            return self._send(200, {"cli": cli, "workspace_dir": ws_str,
                                     "workspace_ready": workspace_ready,
                                     "all_ready": all_ready})

        def _setup_install_cli(self):
            cmd = setup.cli_install_command()
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=300,
                                    encoding="utf-8", errors="replace")
                rc = r.returncode
                out = (r.stdout or "") + (r.stderr or "")
            except Exception as exc:
                rc = -1
                out = str(exc)
            return self._send(200, {"ok": rc == 0, "tail": out[-500:]})

        def _setup_open_login(self):
            cmd = setup.open_login_command()
            try:
                subprocess.Popen(cmd)
            except Exception as exc:
                return self._send(200, {"ok": False, "error": str(exc)})
            return self._send(200, {"ok": True})

        def _setup_install_workspace(self):
            bundle_dir = Path(os.environ.get("KAIROS_BUNDLE_DIR", "."))
            documents = Path.home() / "Documents"
            dest_root = documents if documents.is_dir() else Path.home()
            try:
                result = setup.install_workspace(bundle_dir, dest_root)
            except FileNotFoundError as exc:
                return self._send(400, {"error": str(exc)})
            settings.save({"workspace_dir": result["workspace_dir"]})
            ws_info = _workspace_info_dict(result["workspace_dir"])
            return self._send(200, {"workspace_dir": result["workspace_dir"],
                                     "skills": len(ws_info["skills"])})

        def _storage(self):
            db_path = getattr(state["store"], "_path", None)
            if db_path is None:
                db_path = Path(settings.load()["data_dir"]).expanduser() / "kairos.db"
            db_path = Path(db_path)
            data_dir = str(db_path.parent)
            try:
                db_bytes = os.path.getsize(db_path)
            except OSError:
                db_bytes = 0
            fallback = os.environ.get("KAIROS_STORE_FALLBACK") == "1"
            return self._send(200, {"data_dir": data_dir, "db_bytes": db_bytes,
                                     "fallback": fallback})

        _CTYPES = {".html": "text/html", ".js": "text/javascript",
                   ".css": "text/css", ".svg": "image/svg+xml",
                   ".png": "image/png", ".ico": "image/x-icon"}

        def _static_root(self):
            import os
            from pathlib import Path
            d = os.environ.get("KAIROS_STATIC_DIR")
            if d:
                return Path(d).expanduser().resolve()
            return (Path(__file__).resolve().parent.parent / "app" / "dist").resolve()

        def _serve_static(self):
            root = self._static_root()
            rel = self.path.split("?", 1)[0].lstrip("/")
            target = (root / rel) if rel else (root / "index.html")
            target = target.resolve()
            try:
                target.relative_to(root)
            except ValueError:
                return self._send(404, {"error": "not found"})
            if not target.is_file():
                target = root / "index.html"   # SPA 폴백
                if not target.is_file():
                    return self._send(404, {"error": "spa not built"})
            data = target.read_bytes()
            if target.name == "index.html":
                token_js = ('<script>window.__KAIROS__ = '
                            + json.dumps({"token": token}).replace("<", "\\u003c")
                            + ';</script>')
                data = data.decode("utf-8").replace("</head>", token_js + "</head>", 1).encode("utf-8")
            ctype = self._CTYPES.get(target.suffix.lower(), "application/octet-stream")
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if not self._host_ok():
                return self._send(403, {"error": "forbidden host"})
            if not self._authed():
                return self._send(401, {"error": "unauthorized"})
            if self.path == "/presentations":
                upload = self._multipart()
                if upload is None:
                    return self._send(400, {"error": "bad multipart upload"})
                filename, content, options = upload
                try:
                    job = self._presentation_manager().create(filename, content, options)
                except (OSError, ValueError) as exc:
                    return self._send(400, {"error": str(exc)})
                return self._send(202, job)
            m = re.fullmatch(r"/presentations/([0-9a-f]{12})/retry", self.path)
            if m:
                try:
                    job = self._presentation_manager().retry(m.group(1))
                except ValueError as exc:
                    return self._send(400, {"error": str(exc)})
                return self._send(202, job)
            m = re.fullmatch(
                r"/presentations/([0-9a-f]{12})/(open|reveal)", self.path
            )
            if m:
                return self._open_presentation(
                    m.group(1), reveal=m.group(2) == "reveal"
                )
            body = self._body()
            if body is None:
                return self._send(400, {"error": "bad json"})
            if self.path == "/feedback":
                try:
                    fid = state["store"].add_feedback(int(body["message_id"]),
                                             str(body["kind"]),
                                             str(body.get("payload", "")))
                except (KeyError, TypeError, ValueError) as exc:
                    return self._send(400, {"error": str(exc)})
                return self._send(200, {"id": fid})
            if self.path == "/chat":
                return self._chat(body)
            if self.path == "/rules":
                return self._set_rule_active(body)
            if self.path == "/distill":
                return self._distill()
            if self.path == "/setup/install-cli":
                return self._setup_install_cli()
            if self.path == "/setup/open-login":
                return self._setup_open_login()
            if self.path == "/setup/install-workspace":
                return self._setup_install_workspace()
            return self._send(404, {"error": "not found"})

        def _set_rule_active(self, body: dict):
            try:
                rule_id = int(body["id"])
                active = bool(body["active"])
            except (KeyError, TypeError, ValueError) as exc:
                return self._send(400, {"error": str(exc)})
            state["store"].set_rule_active(rule_id, active)
            return self._send(200, {"ok": True})

        def _distill(self):
            if not _distill_lock.acquire(blocking=False):
                return self._send(409, {"error": "distill already running"})
            try:
                result = distill(state["store"], providers.get("claude").chat, settings.load())
            except Exception as exc:
                return self._send(500, {"error": str(exc)})
            finally:
                _distill_lock.release()
            return self._send(200, result)

        def do_PUT(self):
            if not self._host_ok():
                return self._send(403, {"error": "forbidden host"})
            if not self._authed():
                return self._send(401, {"error": "unauthorized"})
            body = self._body()
            if body is None:
                return self._send(400, {"error": "bad json"})
            if self.path == "/settings":
                return self._put_settings(body)
            if self.path == "/workspace-file":
                return self._save_workspace_file(body)
            return self._send(404, {"error": "not found"})

        def do_DELETE(self):
            if not self._host_ok():
                return self._send(403, {"error": "forbidden host"})
            if not self._authed():
                return self._send(401, {"error": "unauthorized"})
            u = urlparse(self.path)
            if u.path == "/sessions":
                q = parse_qs(u.query)
                try:
                    sid = int(q.get("id", [""])[0])
                except ValueError:
                    return self._send(400, {"error": "bad id"})
                if not state["store"].delete_session(sid):
                    return self._send(404, {"error": "session not found"})
                return self._send(200, {"ok": True})
            return self._send(404, {"error": "not found"})

        def _put_settings(self, patch: dict):
            try:
                settings._validate(patch)
            except ValueError as exc:
                return self._send(400, {"error": str(exc)})

            old_db_path = getattr(state["store"], "_path", None)
            if old_db_path is not None:
                old_db_path = Path(old_db_path)
                old_data_dir = str(old_db_path.parent)
            else:
                old_data_dir = settings.load()["data_dir"]
                old_db_path = Path(old_data_dir).expanduser() / "kairos.db"
            new_data_dir = patch.get("data_dir")
            dir_changed = (
                new_data_dir is not None
                and isinstance(new_data_dir, str)
                and Path(new_data_dir).expanduser() != Path(old_data_dir).expanduser()
            )
            if dir_changed:
                new_dir = Path(new_data_dir).expanduser()
                try:
                    new_dir.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    return self._send(400, {"error": f"cannot create data_dir: {exc}"})
                old_db = old_db_path
                new_db = new_dir / "kairos.db"
                if old_db.exists() and not new_db.exists():
                    try:
                        shutil.copy2(old_db, new_db)
                    except OSError as exc:
                        return self._send(400, {"error": f"cannot copy db: {exc}"})

            raw_before = settings._load_raw()
            try:
                merged = settings.save(patch)
            except ValueError as exc:
                return self._send(400, {"error": str(exc)})
            if dir_changed:
                new_dir = Path(new_data_dir).expanduser()
                try:
                    state["store"] = Store(new_dir / "kairos.db")
                except (OSError, sqlite3.Error) as exc:
                    settings.restore_raw(raw_before)
                    return self._send(400, {"error": f"cannot open store: {exc}"})
                os.environ.pop("KAIROS_STORE_FALLBACK", None)
            return self._send(200, merged)

        def _chat(self, body: dict):
            text = str(body.get("text", "")).strip()
            if not text:
                return self._send(400, {"error": "empty text"})
            cfg = settings.load()
            store = state["store"]
            session_id = body.get("session_id")
            session_title = text[:30]
            if session_id is None:
                session_id = store.create_session(session_title)
            session_id = int(session_id)
            try:
                task_output_dir = output_session_dir(
                    cfg.get("output_dir"), session_id, session_title)
            except OSError:
                task_output_dir = None
            provider_name, cleaned = route(text, cfg)
            # 학습 회상이 꺼져 있으면 빈 채로 남는다 (주입도, 기록도 없음).
            rec: dict = {}
            store.add_message(session_id, "user", [{"type": "text", "text": text}])
            session_ref = _last_session_ref(store, session_id, provider_name)

            self._sse_start()

            def send_status(code: str, label: str, detail: str = ""):
                event = {"type": "status", "code": code, "label": label}
                if detail:
                    event["detail"] = detail
                self._sse(event)

            send_status("preparing", "질문을 정리하고 있습니다")
            if cfg.get("learning_recall_enabled", True):
                send_status("checking_context", "관련 대화와 학습 내용을 확인하고 있습니다")
                rec.update(recall(store, text, session_id))
                rec["rules"] = [r["rule"].replace("\n", " ").strip()
                                for r in store.list_rules(active_only=True)]
                rec["document_edits"] = store.list_document_revisions(limit=3)
                # Search Bible knowledge base — 인사말 수준의 짧은 입력에는
                # 주입하지 않는다 (무관한 구절이 맥락을 오염시키는 것 방지)
                bible_db = documents.default_db_path()
                if bible_db.exists() and len(cleaned) >= 8:
                    try:
                        # 과거 주입 구절이 받은 평가를 순위에 반영한다. 관주
                        # 링크 확장은 documents.search 안에서 기본 동작.
                        bible_refs = documents.search(
                            bible_db, text, limit=3,
                            ref_feedback=store.reference_feedback_weights())
                        _annotate_sermon_history(
                            bible_refs, cfg.get("workspace_dir"))
                        rec["bible_refs"] = bible_refs
                    except Exception:
                        rec["bible_refs"] = []
                prompt, n_recalled = build_prompt(cleaned, rec)
            else:
                prompt, n_recalled = cleaned, 0
            sermon_request = sermon_rag.is_sermon_request(cleaned)
            if sermon_request:
                send_status(
                    "searching_sermons",
                    "과거 설교와 승인된 목사님 원칙을 살펴보고 있습니다",
                    "2019–2026년 설교와 승인·보정 이력을 검색합니다.",
                )
            try:
                sermon_context, n_sermon_rag = sermon_rag.build_sermon_context(
                    cleaned, cfg.get("workspace_dir"), cfg.get("output_dir")
                )
            except (OSError, UnicodeError, ValueError):
                sermon_context, n_sermon_rag = "", 0
            if sermon_context:
                prompt = f"{sermon_context}\n\n---\n{prompt}"
                send_status(
                    "organizing_evidence",
                    "관련 설교 근거를 정리하고 있습니다",
                    f"질문과 관련된 근거 {n_sermon_rag}건을 확인했습니다.",
                )
            location_instruction = output_instruction(task_output_dir)
            if location_instruction:
                prompt = f"{location_instruction}\n\n{prompt}"

            # 결정적 성경 본문 주입: 입력에 "로마서 8:1-4" 같은 참조가 있으면
            # LLM 기억이 아니라 로컬 베들레헴 DB에서 기계적으로 조회해 첨부한다.
            ws_for_bible = cfg.get("workspace_dir")
            if ws_for_bible:
                try:
                    vb = bible_coverage.verses_block(ws_for_bible, text)
                except Exception:
                    vb = ""
                if vb:
                    prompt = f"{vb}\n\n{prompt}"

            send_status("planning", "답변의 흐름을 구성하고 있습니다")
            send_status("generating", "답변을 작성하고 있습니다")
            final = None
            try:
                for ev in providers.get(provider_name).chat(prompt, session_ref=session_ref, cfg=cfg):
                    if ev["type"] in ("delta", "progress"):
                        self._sse(ev)
                    elif ev["type"] == "error":
                        self._sse(ev)
                        return
                    elif ev["type"] == "done":
                        final = ev
            except BrokenPipeError:
                return  # 클라이언트가 끊음: 저장은 아래서 final 있을 때만
            except Exception:
                self._sse({"type": "error", "error": "provider failed"})
                return
            if final is None:
                self._sse({"type": "error", "error": "provider ended without done"})
                return
            send_status("saving", "작업 결과를 정리하고 저장하고 있습니다")
            content = [{"type": "text", "text": final["text"]}]
            if final.get("log"):
                content.append({"type": "log", "text": final["log"]})
            if final.get("session_ref"):
                content.append({"type": "meta", "session_ref": final["session_ref"]})
            mid = store.add_message(session_id, "assistant", content,
                                    provider=provider_name, model=final.get("model"))
            # 이 답변에 어떤 구절이 주입됐는지 남긴다 — 이후 up/down 피드백이
            # 구절 단위 가중으로 되돌아오는 고리.
            injected = rec.get("bible_refs_used")
            if injected:
                try:
                    store.record_injected_refs(
                        mid, [r.get("reference", "") for r in injected])
                except Exception:
                    pass
            try:
                parts = collect(final["text"], cfg.get("workspace_dir"),
                                self._data_dir(), mid)
            except Exception:
                parts = []
            try:
                mirror_outputs(final["text"], cfg.get("workspace_dir"), task_output_dir)
            except Exception:
                pass
            if parts:
                store.append_parts(mid, parts)
            self._sse({"type": "done", "message_id": mid,
                       "session_id": session_id, "provider": provider_name,
                       "recalled": n_recalled, "sermon_rag": n_sermon_rag,
                       "artifacts": len(parts)})

            if (cfg.get("learning_recall_enabled", True)
                    and store.count_undistilled_feedback() >= DISTILL_THRESHOLD):
                def _auto_distill():
                    if not _distill_lock.acquire(blocking=False):
                        return
                    try:
                        distill(store, providers.get("claude").chat, cfg)
                    except Exception:
                        pass
                    finally:
                        _distill_lock.release()
                threading.Thread(target=_auto_distill, daemon=True).start()

    return QuietThreadingHTTPServer((host, port), Handler)
