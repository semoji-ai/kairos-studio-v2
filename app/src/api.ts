// 사이드카 HTTP/SSE 클라이언트. 토큰은 사이드카가 index.html에 주입한다.
declare global {
  interface Window { __KAIROS__?: { token?: string } }
}

const TOKEN = window.__KAIROS__?.token ?? "";
const HDRS = { "Authorization": `Bearer ${TOKEN}`, "Content-Type": "application/json" };

export type Msg = {
  id: number; session_id: number; role: "user" | "assistant";
  content: { type: string; text?: string }[];
  provider?: string | null; model?: string | null;
};
export type Session = { id: number; title: string; created_at: string };
export type ChatEvent =
  | { type: "delta"; text: string }
  | { type: "done"; message_id: number; session_id: number; provider: string }
  | { type: "error"; error: string };

export async function health(): Promise<boolean> {
  try { return (await (await fetch("/health")).json()).ok === true; }
  catch { return false; }
}

export async function listSessions(): Promise<Session[]> {
  const r = await fetch("/sessions", { headers: HDRS });
  return (await r.json()).sessions;
}

export async function listMessages(sessionId: number): Promise<Msg[]> {
  const r = await fetch(`/messages?session_id=${sessionId}`, { headers: HDRS });
  return (await r.json()).messages;
}

export async function sendFeedback(messageId: number, kind: "up" | "down"): Promise<void> {
  await fetch("/feedback", {
    method: "POST", headers: HDRS,
    body: JSON.stringify({ message_id: messageId, kind }),
  });
}

export type Settings = {
  data_dir: string; default_provider: "claude" | "codex";
  routing_rules_enabled: boolean;
  codex_sandbox: "read-only" | "workspace-write";
  claude_permission_mode: "default" | "acceptEdits";
};
export type CliStatus = Record<string, {
  installed: boolean; version: string | null;
  authed: boolean | null; login_hint: string;
}>;
export type StorageInfo = { data_dir: string; db_bytes: number; fallback: boolean };

export async function getSettings(): Promise<Settings> {
  return (await fetch("/settings", { headers: HDRS })).json();
}
export async function putSettings(patch: Partial<Settings>): Promise<Settings> {
  const r = await fetch("/settings", { method: "PUT", headers: HDRS, body: JSON.stringify(patch) });
  if (!r.ok) throw new Error((await r.json()).error ?? `HTTP ${r.status}`);
  return r.json();
}
export async function cliStatus(): Promise<CliStatus> {
  return (await fetch("/cli/status", { headers: HDRS })).json();
}
export async function storageInfo(): Promise<StorageInfo> {
  return (await fetch("/storage", { headers: HDRS })).json();
}

/** POST /chat 후 SSE 스트림을 콜백으로 흘린다. done/error에서 종료. */
export async function chat(
  text: string, sessionId: number | null,
  onEvent: (ev: ChatEvent) => void,
): Promise<void> {
  const resp = await fetch("/chat", {
    method: "POST", headers: HDRS,
    body: JSON.stringify(sessionId == null ? { text } : { text, session_id: sessionId }),
  });
  if (!resp.ok || !resp.body) {
    onEvent({ type: "error", error: `HTTP ${resp.status}` });
    return;
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const frame = buf.slice(0, idx); buf = buf.slice(idx + 2);
      const line = frame.split("\n").find(l => l.startsWith("data: "));
      if (line) onEvent(JSON.parse(line.slice(6)) as ChatEvent);
    }
  }
}
