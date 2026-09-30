import { useEffect, useRef, useState } from "react";
import { discardUpload, learningStatus, retryLearning, startLearning, uploadManuscripts } from "./api";
import type { LearningItem, LearningJob, LearningStatus } from "./api";
import { Emoji } from "./emoji";

type Row = LearningItem & { include: boolean; type: "primary" | "reference" };

const STATUS_LABEL: Record<LearningItem["status"], string> = {
  ok: "학습 가능", empty: "글자 거의 없음", duplicate: "이미 학습함", error: "변환 실패",
};
const JOB_LABEL: Record<LearningJob["status"], string> = {
  queued: "대기 중", absorbing: "흡수 중", profiling: "문체 갱신 중",
  completed: "완료", failed: "실패",
};
const ACCEPT = ".hwp,.hwpx,.docx,.pdf,.md,.markdown,.txt";

export default function Learning() {
  const [status, setStatus] = useState<LearningStatus | null>(null);
  const [uploadId, setUploadId] = useState<string | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  function refresh() {
    learningStatus().then(setStatus).catch(e => setError(String(e)));
  }
  useEffect(() => { refresh(); }, []);
  useEffect(() => {
    const running = status?.jobs.some(j => ["queued", "absorbing", "profiling"].includes(j.status));
    if (!running) return;
    const t = window.setInterval(refresh, 3000);
    return () => window.clearInterval(t);
  }, [status]);

  async function pick(files: FileList | null) {
    if (!files?.length) return;
    setBusy(true); setError("");
    try {
      if (uploadId) await discardUpload(uploadId);
      const res = await uploadManuscripts(Array.from(files));
      setUploadId(res.upload_id);
      setRows(res.items.map(i => ({ ...i, include: i.status === "ok", type: "primary" })));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); setDragging(false); }
  }

  function update(name: string, patch: Partial<Row>) {
    setRows(old => old.map(r => r.name === name ? { ...r, ...patch } : r));
  }

  async function start() {
    if (!uploadId) return;
    setBusy(true); setError("");
    try {
      await startLearning(uploadId, rows.map(r => ({
        name: r.name, title: r.title, type: r.type, include: r.include && r.status === "ok" })));
      setUploadId(null); setRows([]); refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }

  if (status && !status.ready) {
    return (
      <main className="page"><div className="page-inner narrow">
        <header className="page-header"><div>
          <span className="page-eyebrow">MANUSCRIPTS</span><h1>원고 학습</h1></div></header>
        <div className="notice warn">
          <Emoji name="warn" size={16} />{" "}
          {status.reason === "no_workspace"
            ? "설정에서 작업 폴더를 먼저 지정하세요."
            : "대화에서 /publish-setup 으로 워크스페이스를 먼저 초기화하세요."}
        </div>
      </div></main>
    );
  }

  const chosen = rows.filter(r => r.include && r.status === "ok");
  const running = !!status?.jobs.some(j => ["queued", "absorbing", "profiling"].includes(j.status));
  return (
    <main className="page"><div className="page-inner">
      <header className="page-header"><div>
        <span className="page-eyebrow">MANUSCRIPTS</span>
        <h1>원고 학습</h1>
        <p className="hint">목사님 원고와 참고자료를 올리면 위키에 흡수하고, 목사님 원고는 문체 프로필에도 반영합니다.</p>
      </div></header>

      <section className="card">
        <label className={`drop-zone ${dragging ? "is-dragging" : ""}`}
               onDragEnter={e => { e.preventDefault(); setDragging(true); }}
               onDragOver={e => { e.preventDefault(); setDragging(true); }}
               onDragLeave={e => { e.preventDefault(); if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false); }}
               onDrop={e => { e.preventDefault(); pick(e.dataTransfer.files); }}>
          <input ref={inputRef} type="file" multiple accept={ACCEPT}
                 onChange={e => pick(e.target.files)} />
          <span className="drop-icon"><Emoji name="upload" size={44} /></span>
          <strong>{busy ? "변환하는 중…" : "원고 파일을 끌어놓거나 선택하세요"}</strong>
          <small>HWP · HWPX · DOCX · PDF · MD · TXT / 여러 개 가능</small>
        </label>
        {error && <div className="notice error" style={{ marginTop: 12 }}>{error}</div>}
      </section>

      {rows.length > 0 && (
        <section className="card">
          <h3>올린 파일 확인 <span className="hint">{chosen.length}개 학습 예정</span></h3>
          <div className="learn-list">
            {rows.map(r => (
              <div key={r.name} className={`learn-row status-${r.status}`}>
                <input type="checkbox" checked={r.include} disabled={r.status !== "ok"}
                       onChange={e => update(r.name, { include: e.target.checked })}
                       aria-label={`${r.name} 포함`} />
                <div className="learn-main">
                  <input className="learn-title" value={r.title} disabled={r.status !== "ok"}
                         onChange={e => update(r.name, { title: e.target.value })} />
                  <small>{r.name} · {r.chars.toLocaleString()}자 · {STATUS_LABEL[r.status]}
                    {r.reason && ` — ${r.reason}`}
                    {r.duplicate_of && ` (${r.duplicate_of})`}</small>
                  {r.preview && <p className="learn-preview">{r.preview}</p>}
                </div>
                <select value={r.type} disabled={r.status !== "ok"}
                        onChange={e => update(r.name, { type: e.target.value as Row["type"] })}>
                  <option value="primary">목사님 원고</option>
                  <option value="reference">참고자료</option>
                </select>
              </div>
            ))}
          </div>
          <div className="field-row" style={{ marginTop: 14 }}>
            <button className="btn-primary" disabled={busy || running || !chosen.length} onClick={start}>
              학습 시작 ({chosen.length})
            </button>
            {running && <span className="hint">이전 학습이 끝나면 시작할 수 있습니다.</span>}
            <button disabled={busy} onClick={async () => {
              if (uploadId) await discardUpload(uploadId);
              setUploadId(null); setRows([]);
            }}>취소</button>
          </div>
        </section>
      )}

      <section className="card">
        <h3>학습 기록</h3>
        {!status?.jobs.length && (
          <div className="empty-hint"><Emoji name="empty" size={40} /> 아직 학습한 원고가 없습니다.</div>
        )}
        <div className="stack">
          {status?.jobs.map(j => (
            <article key={j.id} className="job-item">
              <div className="job-row">
                <div>
                  <strong>{j.batch_id} · 원고 {j.primary}편 · 참고자료 {j.reference}편</strong>
                  <small>{new Date(j.created_at).toLocaleString("ko-KR")} · {j.stage}</small>
                </div>
                <span className={`job-status ${j.status === "completed" ? "completed" : j.status === "failed" ? "failed" : "running"}`}>
                  {JOB_LABEL[j.status]}
                </span>
              </div>
              {j.error && <div className="job-error">{j.error}</div>}
              {!!j.log.length && <details><summary>작업 로그</summary><pre>{j.log.join("\n\n")}</pre></details>}
              {j.status === "failed" && (
                <button className="retry-action" onClick={async () => {
                  try { await retryLearning(j.id); refresh(); }
                  catch (e) { setError(e instanceof Error ? e.message : String(e)); }
                }}>다시 시도</button>
              )}
            </article>
          ))}
        </div>
      </section>
    </div></main>
  );
}
