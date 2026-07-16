"""HTTP+SSE 서버. stdlib http.server 기반 (기존 kairos-studio 패턴 이식)."""
from __future__ import annotations

import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from core import providers
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


def make_server(host: str, port: int, token: str, store: Store) -> ThreadingHTTPServer:
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
            u = urlparse(self.path)
            if u.path == "/health":
                return self._send(200, {"ok": True})
            # 인증은 API 라우트에만. 그 외 경로는 Task 8에서 정적 서빙이 된다
            # (토큰이 index.html 주입으로 전달되므로 정적은 인증 불가/불요).
            if u.path in ("/sessions", "/messages"):
                if not self._authed():
                    return self._send(401, {"error": "unauthorized"})
                if u.path == "/sessions":
                    return self._send(200, {"sessions": store.list_sessions()})
                q = parse_qs(u.query)
                try:
                    sid = int(q.get("session_id", [""])[0])
                except ValueError:
                    return self._send(400, {"error": "bad session_id"})
                return self._send(200, {"messages": store.list_messages(sid)})
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._authed():
                return self._send(401, {"error": "unauthorized"})
            body = self._body()
            if body is None:
                return self._send(400, {"error": "bad json"})
            if self.path == "/feedback":
                try:
                    fid = store.add_feedback(int(body["message_id"]),
                                             str(body["kind"]),
                                             str(body.get("payload", "")))
                except (KeyError, TypeError, ValueError) as exc:
                    return self._send(400, {"error": str(exc)})
                return self._send(200, {"id": fid})
            if self.path == "/chat":
                return self._chat(body)
            return self._send(404, {"error": "not found"})

        def _chat(self, body: dict):
            text = str(body.get("text", "")).strip()
            if not text:
                return self._send(400, {"error": "empty text"})
            session_id = body.get("session_id")
            if session_id is None:
                session_id = store.create_session(text[:30])
            session_id = int(session_id)
            provider_name, cleaned = route(text)
            store.add_message(session_id, "user", [{"type": "text", "text": text}])
            session_ref = _last_session_ref(store, session_id, provider_name)

            self._sse_start()
            final = None
            try:
                for ev in providers.get(provider_name).chat(cleaned, session_ref=session_ref):
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
