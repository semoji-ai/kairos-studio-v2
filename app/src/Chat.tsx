import { useEffect, useRef, useState } from "react";
import {
  chat, deleteSession, health, listMessages, listReviews, listSessions, sendFeedback,
  workspaceFileUrl,
} from "./api";
import type { ChatEvent, Msg, Session } from "./api";
import Settings from "./Settings";
import BibleCoverage from "./BibleCoverage";
import PresentationStudio from "./PresentationStudio";
import ArtifactPreview from "./ArtifactPreview";
import type { ArtifactPreviewItem } from "./ArtifactPreview";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import coverageIcon from "./assets/icons/coverage.png";
import pptIcon from "./assets/icons/ppt.png";
import reviewIcon from "./assets/icons/review.png";
import settingsIcon from "./assets/icons/settings.png";

type Bubble = Msg | { id: "pending"; role: "assistant"; text: string; log: string };
type StatusEvent = Extract<ChatEvent, { type: "status" }>;

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

function ProgressStatus({
  status,
  elapsed,
}: {
  status: StatusEvent | null;
  elapsed: number;
}) {
  return (
    <div className="chat-progress" role="status" aria-live="polite">
      <span className="chat-progress-dots" aria-hidden="true">
        <i /><i /><i />
      </span>
      <span className="chat-progress-copy">
        <strong>{status?.label || "작업을 준비하고 있습니다"}</strong>
        {status?.detail && <small>{status.detail}</small>}
      </span>
      <time>{elapsed}초</time>
    </div>
  );
}

type ArtifactPart = Msg["content"][number];

function basename(value: string): string {
  let decoded = value;
  try {
    decoded = decodeURIComponent(value);
  } catch {
    // 잘못 인코딩된 외부 링크는 원문으로 비교한다.
  }
  const clean = decoded.split(/[?#]/, 1)[0].replaceAll("\\", "/");
  return clean.slice(clean.lastIndexOf("/") + 1);
}

function decodedLinkPath(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function previewItem(part: ArtifactPart, messageId?: number): ArtifactPreviewItem | null {
  if (!part.artifact || (part.type !== "image" && part.type !== "document")) return null;
  return {
    artifact: part.artifact,
    title: part.title || basename(part.artifact) || "산출물",
    type: part.type,
    sourcePath: part.source_path,
    messageId,
  };
}

function matchingArtifact(
  href: string | undefined,
  parts: ArtifactPart[],
  messageId?: number,
): ArtifactPreviewItem | null {
  if (!href) return null;
  const artifactPath = href.match(/(?:^|\/)artifacts\/(.+?)(?:[?#]|$)/)?.[1];
  if (artifactPath) {
    let decoded = artifactPath;
    try {
      decoded = decodeURIComponent(artifactPath);
    } catch {
      // 잘못 인코딩된 경로도 서버에서 정상적인 404로 처리할 수 있게 둔다.
    }
    const match = parts.find(part => part.artifact === decoded);
    return match ? previewItem(match, messageId) : {
      artifact: decoded,
      title: basename(decoded) || "산출물",
      type: /\.(?:png|jpe?g|webp|gif)$/i.test(decoded) ? "image" : "document",
    };
  }
  const name = basename(href);
  const match = parts.find(part =>
    basename(part.artifact || "").toLowerCase() === name.toLowerCase()
    || basename(part.title || "").toLowerCase() === name.toLowerCase());
  if (match) return previewItem(match, messageId);
  if (/^(?:https?:|mailto:|#)/i.test(href)) return null;
  const image = /\.(?:png|jpe?g|webp|gif)(?:[?#]|$)/i.test(href);
  const document = /\.(?:md|json)(?:[?#]|$)/i.test(href);
  if (!image && !document) return null;
  const localPath = decodedLinkPath(href).replace(/^file:\/\/\//i, "");
  return {
    artifact: "",
    title: name || "산출물",
    type: image ? "image" : "document",
    sourceUrl: workspaceFileUrl(localPath),
    sourcePath: localPath,
    messageId,
  };
}

function safeMarkdownUrl(url: string): string {
  return /^(?:javascript|vbscript|data):/i.test(url.trim()) ? "" : url;
}

export default function Chat() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [pending, setPending] = useState<string | null>(null); // 스트리밍 중 텍스트
  const [pendingLog, setPendingLog] = useState("");
  const [pendingStatus, setPendingStatus] = useState<StatusEvent | null>(null);
  const [pendingStartedAt, setPendingStartedAt] = useState<number | null>(null);
  const [pendingElapsed, setPendingElapsed] = useState(0);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState<"chat" | "settings" | "bible" | "ppt">("chat");
  const [preview, setPreview] = useState<ArtifactPreviewItem | null>(null);
  const [recalled, setRecalled] = useState<Record<number, number>>({}); // message_id -> recalled 건수
  const [sermonRag, setSermonRag] = useState<Record<number, number>>({});
  const [fb, setFb] = useState<Record<number, "up" | "down">>({});      // message_id -> 마지막 피드백
  const [online, setOnline] = useState(true);   // 사이드카 생존 여부
  const [previewWidth, setPreviewWidth] = useState(() => {
    const saved = Number(localStorage.getItem("kairos-preview-width"));
    return saved >= 25 && saved <= 70 ? saved : 44;
  });
  const bottomRef = useRef<HTMLDivElement>(null);
  const chatLayoutRef = useRef<HTMLDivElement>(null);

  useEffect(() => { listSessions().then(setSessions); }, []);
  // 사이드카 생존 감시: 15초마다 /health 확인. 죽으면 배너로 알린다.
  useEffect(() => {
    let stop = false;
    const tick = async () => {
      const ok = await health();
      if (!stop) setOnline(ok);
    };
    tick();
    const t = setInterval(tick, 15000);
    return () => { stop = true; clearInterval(t); };
  }, []);
  useEffect(() => {
    if (sessionId != null) listMessages(sessionId).then(setMsgs);
    else setMsgs([]);
    setPreview(null);
  }, [sessionId]);
  useEffect(() => {
    if (view !== "chat") setPreview(null);
  }, [view]);
  useEffect(() => { bottomRef.current?.scrollIntoView(); }, [msgs, pending, pendingLog]);
  useEffect(() => {
    if (!busy || pendingStartedAt == null) {
      setPendingElapsed(0);
      return;
    }
    const tick = () => setPendingElapsed(
      Math.max(0, Math.floor((Date.now() - pendingStartedAt) / 1000)),
    );
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [busy, pendingStartedAt]);

  function startPreviewResize(event: React.PointerEvent<HTMLDivElement>) {
    event.preventDefault();
    const layout = chatLayoutRef.current;
    if (!layout) return;
    const resize = (moveEvent: PointerEvent) => {
      const rect = layout.getBoundingClientRect();
      const percent = ((rect.right - moveEvent.clientX) / rect.width) * 100;
      const next = Math.min(70, Math.max(25, percent));
      setPreviewWidth(next);
      localStorage.setItem("kairos-preview-width", String(next));
    };
    const stop = () => {
      window.removeEventListener("pointermove", resize);
      window.removeEventListener("pointerup", stop);
      document.body.classList.remove("resizing-preview");
    };
    document.body.classList.add("resizing-preview");
    window.addEventListener("pointermove", resize);
    window.addEventListener("pointerup", stop);
  }

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    setInput(""); setBusy(true); setPending(""); setPendingLog("");
    setPendingStatus({
      type: "status",
      code: "connecting",
      label: "질문을 전달하고 있습니다",
    });
    setPendingStartedAt(Date.now());
    // 낙관적 user 버블
    setMsgs(m => [...m, { id: -1, session_id: sessionId ?? -1, role: "user",
                          content: [{ type: "text", text }] }]);
    let acc = "";
    let logAcc = "";
    try {
      await chat(text, sessionId, ev => {
        if (ev.type === "status") setPendingStatus(ev);
        else if (ev.type === "delta") { acc += ev.text; setPending(acc); }
        else if (ev.type === "progress") { logAcc += ev.text; setPendingLog(logAcc); }
        else if (ev.type === "done") {
          setPending(null); setPendingLog(""); setPendingStatus(null);
          setPendingStartedAt(null); setBusy(false);
          setSessionId(ev.session_id);
          if (ev.recalled) setRecalled(r => ({ ...r, [ev.message_id]: ev.recalled! }));
          if (ev.sermon_rag) setSermonRag(r => ({ ...r, [ev.message_id]: ev.sermon_rag! }));
          listMessages(ev.session_id).then(setMsgs);   // 서버 진실로 동기화
          listSessions().then(setSessions);
        } else {
          setPending(null); setPendingLog(""); setPendingStatus(null);
          setPendingStartedAt(null); setBusy(false);
          setMsgs(m => [...m, { id: -2, session_id: sessionId ?? -1, role: "assistant",
                                content: [{ type: "text", text: `⚠️ ${ev.error}` }] }]);
        }
      });
    } catch {
      setPending(null); setPendingLog(""); setPendingStatus(null);
      setPendingStartedAt(null); setBusy(false);
      setMsgs(m => [...m, { id: -2, session_id: sessionId ?? -1, role: "assistant",
                            content: [{ type: "text", text: "⚠️ 연결 실패: 사이드카가 실행 중인지 확인하세요" }] }]);
    }
  }

  const bubbles: Bubble[] = pending == null ? msgs
    : [...msgs, { id: "pending", role: "assistant", text: pending, log: pendingLog }];

  async function openLatestReview() {
    try {
      const reviews = await listReviews();
      if (!reviews.length) {
        alert("검토할 승인 후보가 없습니다.");
        return;
      }
      const review = reviews[0];
      setView("chat");
      setPreview({
        artifact: "",
        title: `${review.title} · ${review.decided}/${review.total}`,
        type: "document",
        sourceUrl: workspaceFileUrl(review.path),
        sourcePath: review.path,
      });
    } catch {
      alert("승인 검토 목록을 불러오지 못했습니다.");
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", fontFamily: "sans-serif" }}>
      {!online && (
        <div style={{ background: "#c0392b", color: "#fff", padding: "6px 14px",
                      fontSize: 13, textAlign: "center" }}>
          ⚠️ 백엔드(사이드카)와 연결이 끊겼습니다. 앱을 껐다 다시 실행해 주세요.
          응답·성경 커버리지 등 모든 기능이 이 상태에서는 동작하지 않습니다.
        </div>
      )}
      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
      <aside style={{ width: 220, borderRight: "1px solid #ddd", overflowY: "auto" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 4, margin: 8 }}>
          <button style={{ padding: "8px 10px", fontWeight: 600, textAlign: "left" }}
                  onClick={() => { setSessionId(null); setView("chat"); }}>＋ 새 대화</button>
          {([
            { key: "bible", icon: coverageIcon, label: "설교 커버리지",
              on: () => setView(v => v === "bible" ? "chat" : "bible"), active: view === "bible" },
            { key: "ppt", icon: pptIcon, label: "PPT 만들기",
              on: () => setView(v => v === "ppt" ? "chat" : "ppt"), active: view === "ppt" },
            { key: "review", icon: reviewIcon, label: "검토·승인",
              on: openLatestReview, active: false },
            { key: "settings", icon: settingsIcon, label: "설정",
              on: () => setView(v => v === "chat" ? "settings" : "chat"), active: view === "settings" },
          ] as const).map(b => (
            <button key={b.key} onClick={b.on}
                    style={{ display: "flex", alignItems: "center", gap: 8,
                             padding: "6px 10px", textAlign: "left", cursor: "pointer",
                             border: "1px solid #e2e2e8", borderRadius: 6,
                             background: b.active ? "#eef" : "#fafafa" }}>
              <img src={b.icon} width={22} height={22} alt=""
                   style={{ borderRadius: 5, flexShrink: 0 }} />
              <span>{b.label}</span>
            </button>
          ))}
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
      ) : view === "ppt" ? (
        <PresentationStudio />
      ) : (
      <div className="chat-with-preview" ref={chatLayoutRef}>
      <main className="chat-main">
        <div style={{ flex: 1, overflowY: "auto", padding: 16 }}>
          {bubbles.map((b, i) => {
            const isPending = !("content" in b);
            const text = isPending ? b.text : textOf(b as Msg);
            const log = isPending ? b.log : logOf(b as Msg);
            const m = b as Msg;
            const artifactParts = !isPending
              ? m.content.filter(p => p.type === "image" || p.type === "document")
              : [];
            return (
              <div key={i} style={{ margin: "8px 0",
                                    textAlign: b.role === "user" ? "right" : "left" }}>
                <div className={b.role === "assistant" ? "md-bubble" : undefined}
                     style={{ display: "inline-block", padding: "8px 12px", borderRadius: 8,
                              whiteSpace: b.role === "user" ? "pre-wrap" : undefined,
                              textAlign: "left", maxWidth: "80%",
                              background: b.role === "user" ? "#dbeafe" : "#f3f4f6" }}>
                  {b.role === "assistant"
                    ? <>{isPending && (
                          <ProgressStatus status={pendingStatus} elapsed={pendingElapsed} />
                        )}
                        <WorkLog text={log} active={isPending} />
                        {text && <ReactMarkdown
                          remarkPlugins={[remarkGfm]}
                          urlTransform={safeMarkdownUrl}
                          components={{
                            a: ({ href, children, ...props }) => {
                              const item = matchingArtifact(href, artifactParts, m.id);
                              return item ? (
                                <a
                                  {...props}
                                  href={`/artifacts/${item.artifact}`}
                                  className="artifact-inline-link"
                                  onClick={event => {
                                    event.preventDefault();
                                    setPreview(item);
                                  }}
                                >{children}</a>
                              ) : <a {...props} href={href}>{children}</a>;
                            },
                          }}
                        >{text}</ReactMarkdown>}
                        {isPending && text && "▌"}</>
                    : <>{text}{isPending && "▌"}</>}
                  {artifactParts.length > 0 && (
                    <div className="artifact-list">
                      {artifactParts.map((part, pi) => {
                        const item = previewItem(part, m.id);
                        if (!item) return null;
                        return (
                          <button key={`${item.artifact}-${pi}`} type="button"
                                  className="artifact-chip" onClick={() => setPreview(item)}>
                            <span>{item.type === "image" ? "▧" : "▤"}</span>
                            <span>{item.title}</span>
                            <small>미리보기</small>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
                {!isPending && m.role === "assistant" && m.id > 0 && (
                  <div style={{ fontSize: 12, color: "#888" }}>
                    {m.provider}
                    {recalled[m.id] > 0 && <span> 🧠 과거 대화 {recalled[m.id]}건 참조</span>}
                    {sermonRag[m.id] > 0 && <span> ⛪ 목사님 설교 RAG {sermonRag[m.id]}건 참조</span>}
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
      {preview && (
        <>
          <div className="artifact-resizer" role="separator" aria-orientation="vertical"
               aria-label="미리보기 패널 크기 조절" onPointerDown={startPreviewResize} />
          <ArtifactPreview item={preview} widthPercent={previewWidth}
                           onClose={() => setPreview(null)} />
        </>
      )}
      </div>
      )}
      </div>
    </div>
  );
}
