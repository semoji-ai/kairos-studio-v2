"""HTTP+SSE 서버. stdlib http.server 기반 (기존 kairos-studio 패턴 이식)."""
from __future__ import annotations

import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from core import bible_coverage, documents, providers, settings, setup
from core.artifacts import collect
from core.distill import distill
from core.recall import recall
from core.router import route
from core.store import Store

_INJECT_BUDGET = 1500
DISTILL_THRESHOLD = 10
_distill_lock = threading.Lock()


def build_prompt(text: str, rec: dict) -> tuple[str, int]:
    """스펙 ③ 형식으로 회상 결과를 원문 앞에 조립.

    반환: (프롬프트, 주입된 스니펫 수). 회상 결과가 전부 비어 있으면 (text, 0).
    1,500자 하드캡 초과 시 스니펫을 뒤에서부터 제거해 캡 이하로 맞춘다
    (corrections/avoid는 우선 보존). 캡은 주입 블록의 길이만 측정하며,
    사용자 텍스트의 길이는 무시한다.
    """
    snippets = list(rec.get("snippets") or [])
    avoid = list(rec.get("avoid") or [])
    corrections = list(rec.get("corrections") or [])
    rules = list(rec.get("rules") or [])
    bible_refs = list(rec.get("bible_refs") or [])

    def render_block(snips: list[dict], rls: list[str], refs: list[dict]) -> str:
        blocks = []
        if rls:
            lines = "\n".join(f"- {r}" for r in rls)
            blocks.append(f"[학습된 규칙 — 항상 준수]\n{lines}")
        if refs:
            # 원전분해 등 대용량 항목이 프롬프트를 오염시키지 않게 항목당 길이 제한
            lines = "\n".join(
                f"[{r.get('reference', '')}] {str(r.get('content', ''))[:180]}"
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
        if not blocks:
            return ""
        return "\n\n".join(blocks)

    block = render_block(snippets, rules, bible_refs)
    while block and len(block) > _INJECT_BUDGET and snippets:
        snippets = snippets[:-1]
        block = render_block(snippets, rules, bible_refs)
    # 스니펫을 다 줄여도 여전히 캡 초과면 규칙을 오래된 것부터(리스트 끝) 줄인다.
    # store.list_rules()는 id 내림차순(최신 우선)이므로 끝을 자르면 최신이 남는다.
    while block and len(block) > _INJECT_BUDGET and rules:
        rules = rules[:-1]
        block = render_block(snippets, rules, bible_refs)
    # 마지막으로 성경 자료도 필요시 줄인다.
    while block and len(block) > _INJECT_BUDGET and bible_refs:
        bible_refs = bible_refs[:-1]
        block = render_block(snippets, rules, bible_refs)

    if not block:
        return text, 0
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
            if u.path in ("/sessions", "/messages", "/settings", "/storage", "/cli/status",
                          "/workspace/info", "/rules", "/setup/status", "/bible/coverage"):
                if not self._authed():
                    return self._send(401, {"error": "unauthorized"})
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
            return self._serve_static()

        def _data_dir(self) -> Path:
            db_path = getattr(state["store"], "_path", None)
            if db_path is None:
                db_path = Path(settings.load()["data_dir"]).expanduser() / "kairos.db"
            return Path(db_path).parent

        _ARTIFACT_CTYPES = {".png": "image/png", ".jpg": "image/jpeg",
                             ".jpeg": "image/jpeg", ".webp": "image/webp",
                             ".gif": "image/gif", ".md": "text/markdown"}

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
            if session_id is None:
                session_id = store.create_session(text[:30])
            session_id = int(session_id)
            provider_name, cleaned = route(text, cfg)
            store.add_message(session_id, "user", [{"type": "text", "text": text}])
            session_ref = _last_session_ref(store, session_id, provider_name)

            if cfg.get("learning_recall_enabled", True):
                rec = recall(store, text, session_id)
                rec["rules"] = [r["rule"].replace("\n", " ").strip()
                                for r in store.list_rules(active_only=True)]
                # Search Bible knowledge base — 인사말 수준의 짧은 입력에는
                # 주입하지 않는다 (무관한 구절이 맥락을 오염시키는 것 방지)
                bible_db = Path(__file__).parent.parent / "bible_documents.db"
                if bible_db.exists() and len(cleaned) >= 8:
                    try:
                        bible_refs = documents.search(bible_db, text, limit=3)
                        rec["bible_refs"] = bible_refs
                    except Exception:
                        rec["bible_refs"] = []
                prompt, n_recalled = build_prompt(cleaned, rec)
            else:
                prompt, n_recalled = cleaned, 0

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

            self._sse_start()
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
            content = [{"type": "text", "text": final["text"]}]
            if final.get("log"):
                content.append({"type": "log", "text": final["log"]})
            if final.get("session_ref"):
                content.append({"type": "meta", "session_ref": final["session_ref"]})
            mid = store.add_message(session_id, "assistant", content,
                                    provider=provider_name, model=final.get("model"))
            try:
                parts = collect(final["text"], cfg.get("workspace_dir"),
                                self._data_dir(), mid)
            except Exception:
                parts = []
            if parts:
                store.append_parts(mid, parts)
            self._sse({"type": "done", "message_id": mid,
                       "session_id": session_id, "provider": provider_name,
                       "recalled": n_recalled, "artifacts": len(parts)})

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

    return ThreadingHTTPServer((host, port), Handler)
