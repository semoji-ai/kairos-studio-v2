"""HTTP+SSE 서버. stdlib http.server 기반 (기존 kairos-studio 패턴 이식)."""
from __future__ import annotations

import json
import os
import secrets
import shutil
import sqlite3
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from core import providers, settings
from core.router import route
from core.store import Store


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
            if u.path in ("/sessions", "/messages", "/settings", "/storage", "/cli/status"):
                if not self._authed():
                    return self._send(401, {"error": "unauthorized"})
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
            return self._serve_static()

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
            return self._send(404, {"error": "not found"})

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

            prior_settings = settings.load()
            try:
                merged = settings.save(patch)
            except ValueError as exc:
                return self._send(400, {"error": str(exc)})
            if dir_changed:
                new_dir = Path(new_data_dir).expanduser()
                try:
                    state["store"] = Store(new_dir / "kairos.db")
                except (OSError, sqlite3.Error) as exc:
                    settings.save({"data_dir": prior_settings["data_dir"]})
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

            self._sse_start()
            final = None
            try:
                for ev in providers.get(provider_name).chat(cleaned, session_ref=session_ref, cfg=cfg):
                    if ev["type"] == "delta":
                        self._sse(ev)
                    elif ev["type"] == "error":
                        self._sse(ev)
                        return
                    elif ev["type"] == "done":
                        final = ev
            except BrokenPipeError:
                return  # 클라이언트가 끊음: 저장은 아래서 final 있을 때만
            if final is None:
                self._sse({"type": "error", "error": "provider ended without done"})
                return
            content = [{"type": "text", "text": final["text"]}]
            if final.get("session_ref"):
                content.append({"type": "meta", "session_ref": final["session_ref"]})
            mid = store.add_message(session_id, "assistant", content,
                                    provider=provider_name, model=final.get("model"))
            self._sse({"type": "done", "message_id": mid,
                       "session_id": session_id, "provider": provider_name})

    return ThreadingHTTPServer((host, port), Handler)
