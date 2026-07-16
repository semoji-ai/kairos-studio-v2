import { useEffect, useRef, useState } from "react";
import { chat, listMessages, listSessions, sendFeedback } from "./api";
import type { Msg, Session } from "./api";

type Bubble = Msg | { id: "pending"; role: "assistant"; text: string };

function textOf(m: Msg): string {
  return m.content.filter(p => p.type === "text").map(p => p.text ?? "").join("");
}

export default function Chat() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [pending, setPending] = useState<string | null>(null); // 스트리밍 중 텍스트
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => { listSessions().then(setSessions); }, []);
  useEffect(() => {
    if (sessionId != null) listMessages(sessionId).then(setMsgs);
    else setMsgs([]);
  }, [sessionId]);
  useEffect(() => { bottomRef.current?.scrollIntoView(); }, [msgs, pending]);

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    setInput(""); setBusy(true); setPending("");
    // 낙관적 user 버블
    setMsgs(m => [...m, { id: -1, session_id: sessionId ?? -1, role: "user",
                          content: [{ type: "text", text }] }]);
    let acc = "";
    await chat(text, sessionId, ev => {
      if (ev.type === "delta") { acc += ev.text; setPending(acc); }
      else if (ev.type === "done") {
        setPending(null); setBusy(false);
        setSessionId(ev.session_id);
        listMessages(ev.session_id).then(setMsgs);   // 서버 진실로 동기화
        listSessions().then(setSessions);
      } else {
        setPending(null); setBusy(false);
        setMsgs(m => [...m, { id: -2, session_id: sessionId ?? -1, role: "assistant",
                              content: [{ type: "text", text: `⚠️ ${ev.error}` }] }]);
      }
    });
  }

  const bubbles: Bubble[] = pending == null ? msgs
    : [...msgs, { id: "pending", role: "assistant", text: pending }];

  return (
    <div style={{ display: "flex", height: "100vh", fontFamily: "sans-serif" }}>
      <aside style={{ width: 220, borderRight: "1px solid #ddd", overflowY: "auto" }}>
        <button style={{ margin: 8 }} onClick={() => setSessionId(null)}>+ 새 대화</button>
        {sessions.map(s => (
          <div key={s.id} onClick={() => setSessionId(s.id)}
               style={{ padding: 8, cursor: "pointer",
                        background: s.id === sessionId ? "#eef" : undefined }}>
            {s.title}
          </div>
        ))}
      </aside>
      <main style={{ flex: 1, display: "flex", flexDirection: "column" }}>
        <div style={{ flex: 1, overflowY: "auto", padding: 16 }}>
          {bubbles.map((b, i) => {
            const isPending = !("content" in b);
            const text = isPending ? b.text : textOf(b as Msg);
            const m = b as Msg;
            return (
              <div key={i} style={{ margin: "8px 0",
                                    textAlign: b.role === "user" ? "right" : "left" }}>
                <div style={{ display: "inline-block", padding: "8px 12px", borderRadius: 8,
                              whiteSpace: "pre-wrap", maxWidth: "80%",
                              background: b.role === "user" ? "#dbeafe" : "#f3f4f6" }}>
                  {text}{isPending && "▌"}
                </div>
                {!isPending && m.role === "assistant" && m.id > 0 && (
                  <div style={{ fontSize: 12, color: "#888" }}>
                    {m.provider}
                    <button onClick={() => sendFeedback(m.id, "up")}> 👍</button>
                    <button onClick={() => sendFeedback(m.id, "down")}> 👎</button>
                  </div>
                )}
              </div>
            );
          })}
          <div ref={bottomRef} />
        </div>
        <div style={{ display: "flex", padding: 8, borderTop: "1px solid #ddd" }}>
          <textarea value={input} onChange={e => setInput(e.target.value)}
                    onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
                    placeholder="메시지 (@claude / @codex 로 강제 지정)"
                    style={{ flex: 1, resize: "none", height: 60 }} />
          <button onClick={send} disabled={busy} style={{ marginLeft: 8 }}>보내기</button>
        </div>
      </main>
    </div>
  );
}
