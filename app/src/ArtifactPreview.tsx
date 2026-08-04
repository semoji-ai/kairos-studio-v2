import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { saveWorkspaceDocument } from "./api";
import TheologyReview from "./TheologyReview";
import {
  isTheologyReview,
  type TheologyReviewDocument,
} from "./theologyReviewTypes";

export type ArtifactPreviewItem = {
  artifact: string;
  title: string;
  type: "image" | "document";
  sourceUrl?: string;
  sourcePath?: string;
  messageId?: number;
};

function extensionOf(name: string): string {
  const clean = name.split(/[?#]/, 1)[0];
  const dot = clean.lastIndexOf(".");
  return dot >= 0 ? clean.slice(dot).toLowerCase() : "";
}

export default function ArtifactPreview({
  item,
  onClose,
  widthPercent,
}: {
  item: ArtifactPreviewItem;
  onClose: () => void;
  widthPercent: number;
}) {
  const [body, setBody] = useState("");
  const [loading, setLoading] = useState(item.type === "document");
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveNotice, setSaveNotice] = useState("");
  const [review, setReview] = useState<TheologyReviewDocument | null>(null);
  const url = item.sourceUrl || `/artifacts/${item.artifact}`;
  const extension = extensionOf(item.sourcePath || item.title || item.artifact);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  useEffect(() => {
    if (item.type !== "document" || extension === ".pdf") return;
    const controller = new AbortController();
    let current = true;
    setBody("");
    setDraft("");
    setEditing(false);
    setReview(null);
    setSaveNotice("");
    setError("");
    setLoading(true);
    fetch(url, { signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.text();
      })
      .then(text => {
        if (!current) return;
        setError("");
        setBody(text);
        setDraft(text);
        if (extension === ".json") {
          try {
            const parsed: unknown = JSON.parse(text);
            if (isTheologyReview(parsed)) setReview(parsed);
          } catch {
            // 일반 JSON이나 구문 오류가 있는 문서는 평문으로 보여 준다.
          }
        }
      })
      .catch(error => {
        if (current && error.name !== "AbortError") {
          setError(`문서를 불러오지 못했습니다. (${error.message || "요청 실패"})`);
        }
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
      controller.abort();
    };
  }, [extension, item.artifact, item.type, url]);

  async function save() {
    if (!item.sourcePath || saving) return;
    setSaving(true);
    setError("");
    setSaveNotice("");
    try {
      const result = await saveWorkspaceDocument(item.sourcePath, draft, item.messageId);
      setBody(draft);
      setEditing(false);
      setSaveNotice(result.changed
        ? `새 버전 저장 완료 · +${result.additions} / -${result.deletions} · 스타일 학습 반영`
        : "변경된 내용이 없습니다.");
    } catch (error) {
      setError(error instanceof Error ? error.message : "문서를 저장하지 못했습니다.");
    } finally {
      setSaving(false);
    }
  }

  async function saveReview() {
    if (!item.sourcePath || !review || saving) return;
    setSaving(true);
    setError("");
    setSaveNotice("");
    try {
      const pending = review.claims.some(claim => claim.status === "pending");
      const next: TheologyReviewDocument = {
        ...review,
        review_status: pending ? "in_review" : "reviewed",
        updated_at: new Date().toISOString(),
      };
      const content = `${JSON.stringify(next, null, 2)}\n`;
      const result = await saveWorkspaceDocument(item.sourcePath, content, item.messageId);
      setReview(next);
      setBody(content);
      const approved = next.claims.filter(claim => claim.status === "approved").length;
      const historical = next.claims.filter(
        claim => claim.status === "historical_verified"
      ).length;
      const undecided = next.claims.filter(claim => claim.status === "pending").length;
      const promoted = result.promoted?.approved ?? approved;
      const promotedHistorical = result.promoted?.historical ?? historical;
      setSaveNotice(result.changed
        ? `검토 결과와 RAG 프로필 저장 완료 · 현재 승인 ${promoted}건 · 과거 확인 ${promotedHistorical}건 · 미검토 ${undecided}건`
        : "변경된 검토 결과가 없습니다.");
    } catch (error) {
      setError(error instanceof Error ? error.message : "검토 결과를 저장하지 못했습니다.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <aside className="artifact-preview" aria-label="산출물 미리보기"
           style={{ flexBasis: `${widthPercent}%` }}>
      <header className="artifact-preview-header">
        <div>
          <span>산출물 미리보기</span>
          <strong title={item.title}>{item.title}</strong>
        </div>
        <div className="artifact-preview-actions">
          {review && item.sourcePath && (
            <button type="button" className="save review-save"
                    onClick={saveReview} disabled={saving}>
              {saving ? "저장 중…" : "검토 결과 저장"}
            </button>
          )}
          {!review && item.type === "document" && extension === ".md" && item.sourcePath && (
            editing ? (
              <>
                <button type="button" onClick={() => { setDraft(body); setEditing(false); }}
                        disabled={saving}>취소</button>
                <button type="button" className="save" onClick={save} disabled={saving}>
                  {saving ? "저장 중…" : "버전 저장"}
                </button>
              </>
            ) : (
              <button type="button" onClick={() => setEditing(true)}>편집</button>
            )
          )}
          <a href={url} download={item.title} title="파일 다운로드">다운로드</a>
          <button type="button" onClick={onClose} aria-label="미리보기 닫기">×</button>
        </div>
      </header>
      {saveNotice && <div className="artifact-save-notice">{saveNotice}</div>}
      <div className={`artifact-preview-body ${item.type}`}>
        {item.type === "image" ? (
          <img src={url} alt={item.title} />
        ) : extension === ".pdf" ? (
          <iframe src={url} title={item.title} />
        ) : loading ? (
          <div className="artifact-preview-status">문서를 불러오는 중…</div>
        ) : error ? (
          <div className="artifact-preview-status error">{error}</div>
        ) : review ? (
          <TheologyReview value={review} onChange={setReview} />
        ) : editing ? (
          <textarea className="artifact-editor" value={draft}
                    onChange={event => setDraft(event.target.value)}
                    spellCheck />
        ) : extension === ".md" || extension === ".markdown" ? (
          <article className="artifact-markdown">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{body}</ReactMarkdown>
          </article>
        ) : (
          <pre className="artifact-plain-text">{body}</pre>
        )}
      </div>
    </aside>
  );
}
