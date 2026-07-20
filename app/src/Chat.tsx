import { useEffect, useRef, useState } from "react";
import { chat, deleteSession, listMessages, listSessions, sendFeedback } from "./api";
import type { Msg, Session } from "./api";
import Settings from "./Settings";
import BibleCoverage from "./BibleCoverage";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type Bubble = Msg | { id: "pending"; role: "assistant"; text: string; log: string };

function textOf(m: Msg): string {
  return m.content.filter(p => p.type === "text").map(p => p.text ?? "").join("");
}

function logOf(m: Msg): string {
  return m.content.filter(p => p.type === "log").map(p => p.text ?? "").join("");
}

function WorkLog({ text, active = false }: { text: string; active?: boolean }) {
  if (!text && !active) return null;
  return (
    <details className="work-log">
      <summary>{active ? "작업 로그 · 생성 중" : "작업 로그"}</summary>
      <div className="work-log-body">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{text || "자료를 확인하고 있습니다…"}</ReactMarkdown>
      </div>
    </details>
  );
}

function DocBody({ artifact, open }: { artifact?: string; open: boolean }) {
  const [body, setBody] = useState<string | null>(null);
  useEffect(() => {
    if (open && body == null && artifact) {
      fetch("/artifacts/" + artifact)
        .then(r => r.text())
        .then(setBody)
        .catch(() => setBody("(불러오기 실패)"));
    }
  }, [open, body, artifact]);
  return <pre style={{ whiteSpace: "pre-wrap" }}>{body}</pre>;
}

function PartDetails({ artifact, title }: { artifact?: string; title?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <details style={{ marginTop: 8 }} onToggle={e => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>📄 {title ?? artifact}</summary>
      <DocBody artifact={artifact} open={open} />
    </details>
  );
}

export default function Chat() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [pending, setPending] = useState<string | null>(null); // 스트리밍 중 텍스트
  const [pendingLog, setPendingLog] = useState("");
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState<"chat" | "settings" | "bible">("chat");
  const [recalled, setRecalled] = useState<Record<number, number>>({}); // message_id -> recalled 건수
  const [fb, setFb] = useState<Record<number, "up" | "down">>({});      // message_id -> 마지막 피드백
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => { listSessions().then(setSessions); }, []);
  useEffect(() => {
    if (sessionId != null) listMessages(sessionId).then(setMsgs);
    else setMsgs([]);
  }, [sessionId]);
  useEffect(() => { bottomRef.current?.scrollIntoView(); }, [msgs, pending, pendingLog]);

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    setInput(""); setBusy(true); setPending(""); setPendingLog("");
    // 낙관적 user 버블
    setMsgs(m => [...m, { id: -1, session_id: sessionId ?? -1, role: "user",
                          content: [{ type: "text", text }] }]);
    let acc = "";
    let logAcc = "";
    try {
      await chat(text, sessionId, ev => {
        if (ev.type === "delta") { acc += ev.text; setPending(acc); }
        else if (ev.type === "progress") { logAcc += ev.text; setPendingLog(logAcc); }
        else if (ev.type === "done") {
          setPending(null); setPendingLog(""); setBusy(false);
          setSessionId(ev.session_id);
          if (ev.recalled) setRecalled(r => ({ ...r, [ev.message_id]: ev.recalled! }));
          listMessages(ev.session_id).then(setMsgs);   // 서버 진실로 동기화
          listSessions().then(setSessions);
        } else {
          setPending(null); setPendingLog(""); setBusy(false);
          setMsgs(m => [...m, { id: -2, session_id: sessionId ?? -1, role: "assistant",
                                content: [{ type: "text", text: `⚠️ ${ev.error}` }] }]);
        }
      });
    } catch {
      setPending(null); setPendingLog(""); setBusy(false);
      setMsgs(m => [...m, { id: -2, session_id: sessionId ?? -1, role: "assistant",
                            content: [{ type: "text", text: "⚠️ 연결 실패: 사이드카가 실행 중인지 확인하세요" }] }]);
    }
  }

  const bubbles: Bubble[] = pending == null ? msgs
    : [...msgs, { id: "pending", role: "assistant", text: pending, log: pendingLog }];

  return (
    <div style={{ display: "flex", height: "100vh", fontFamily: "sans-serif" }}>
      <aside style={{ width: 220, borderRight: "1px solid #ddd", overflowY: "auto" }}>
        <div style={{ display: "flex", alignItems: "center", margin: 8 }}>
          <button style={{ flex: 1 }} onClick={() => { setSessionId(null); setView("chat"); }}>+ 새 대화</button>
          <button style={{ marginLeft: 6 }} onClick={() => setView(v => v === "bible" ? "chat" : "bible")}
                  title="성경 설교 커버리지">📖</button>
          <button style={{ marginLeft: 6 }} onClick={() => setView(v => v === "chat" ? "settings" : "chat")}
                  title="설정">⚙️</button>
        </div>
        {sessions.map(s => (
          <div key={s.id} onClick={() => { setSessionId(s.id); setView("chat"); }}
               style={{ padding: 8, cursor: "pointer", display: "flex",
                        alignItems: "center", gap: 4,
                        background: s.id === sessionId ? "#eef" : undefined }}>
            <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis",
                           whiteSpace: "nowrap" }}>{s.title}</span>
            <button title="대화 삭제"
                    onClick={async (e) => {
                      e.stopPropagation();
                      if (!confirm(`"${s.title}" 대화를 삭제할까요?`)) return;
                      await deleteSession(s.id);
                      if (s.id === sessionId) { setSessionId(null); setMsgs([]); }
                      listSessions().then(setSessions);
                    }}
                    style={{ border: "none", background: "transparent",
                             cursor: "pointer", opacity: 0.55 }}>🗑</button>
          </div>
        ))}
      </aside>
      {view === "settings" ? (
        <Settings onClose={() => setView("chat")} />
      ) : view === "bible" ? (
        <BibleCoverage />
      ) : (
      <main style={{ flex: 1, display: "flex", flexDirection: "column" }}>
        <div style={{ flex: 1, overflowY: "auto", padding: 16 }}>
          {bubbles.map((b, i) => {
            const isPending = !("content" in b);
            const text = isPending ? b.text : textOf(b as Msg);
            const log = isPending ? b.log : logOf(b as Msg);
            const m = b as Msg;
            return (
              <div key={i} style={{ margin: "8px 0",
                                    textAlign: b.role === "user" ? "right" : "left" }}>
                <div className={b.role === "assistant" ? "md-bubble" : undefined}
                     style={{ display: "inline-block", padding: "8px 12px", borderRadius: 8,
                              whiteSpace: b.role === "user" ? "pre-wrap" : undefined,
                              textAlign: "left", maxWidth: "80%",
                              background: b.role === "user" ? "#dbeafe" : "#f3f4f6" }}>
                  {b.role === "assistant"
                    ? <><WorkLog text={log} active={isPending} />
                        {text && <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>}
                        {isPending && text && "▌"}</>
                    : <>{text}{isPending && "▌"}</>}
                  {!isPending && m.role === "assistant" && m.content
                    .filter(p => p.type === "image" || p.type === "document")
                    .map((p, pi) => p.type === "image" ? (
                      <img key={pi} src={"/artifacts/" + p.artifact}
                           style={{ maxWidth: "100%", borderRadius: 8, display: "block", marginTop: 8 }} />
                    ) : (
                      <PartDetails key={pi} artifact={p.artifact} title={p.title} />
                    ))}
                </div>
                {!isPending && m.role === "assistant" && m.id > 0 && (
                  <div style={{ fontSize: 12, color: "#888" }}>
                    {m.provider}
                    {recalled[m.id] > 0 && <span> 🧠 과거 대화 {recalled[m.id]}건 참조</span>}
                    {(["up", "down"] as const).map(kind => (
                      <button key={kind}
                              onClick={async () => {
                                if (fb[m.id] === kind) return;  // 같은 피드백 중복 방지
                                await sendFeedback(m.id, kind);
                                setFb(f => ({ ...f, [m.id]: kind }));
                              }}
                              title={kind === "up" ? "좋아요 — 이런 답변을 우선 회상"
                                                   : "싫어요 — 이런 답변은 회피"}
                              style={{ marginLeft: 4, border: "none", borderRadius: 6,
                                       padding: "2px 7px", cursor: "pointer",
                                       background: fb[m.id] === kind ? "#c9e5cf" : "transparent",
                                       opacity: fb[m.id] && fb[m.id] !== kind ? 0.35 : 1 }}>
                        {kind === "up" ? "👍" : "👎"}
                      </button>
                    ))}
                    {fb[m.id] && <span style={{ marginLeft: 6, color: "#2a7" }}>학습에 반영됨</span>}
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
      )}
    </div>
  );
}
