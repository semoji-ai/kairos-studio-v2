// 사이드카 HTTP/SSE 클라이언트. 토큰은 사이드카가 index.html에 주입한다.
declare global {
  interface Window { __KAIROS__?: { token?: string } }
}

const TOKEN = window.__KAIROS__?.token ?? "";
const HDRS = { "Authorization": `Bearer ${TOKEN}`, "Content-Type": "application/json" };

export function workspaceFileUrl(path: string): string {
  const params = new URLSearchParams({ path, token: TOKEN });
  return `/workspace-file?${params.toString()}`;
}

export type Msg = {
  id: number; session_id: number; role: "user" | "assistant";
  content: {
    type: string; text?: string; artifact?: string; title?: string; source_path?: string;
  }[];
  provider?: string | null; model?: string | null;
};
export type Session = { id: number; title: string; created_at: string };
export type ChatEvent =
  | { type: "delta"; text: string }
  | { type: "progress"; text: string }
  | { type: "status"; code: string; label: string; detail?: string }
  | { type: "done"; message_id: number; session_id: number; provider: string; recalled?: number; sermon_rag?: number; artifacts?: number }
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

export async function deleteSession(sessionId: number): Promise<void> {
  const r = await fetch(`/sessions?id=${sessionId}`, { method: "DELETE", headers: HDRS });
  if (!r.ok) throw new Error((await r.json()).error ?? `HTTP ${r.status}`);
}

export type BibleSermonRef = { title: string; date: string; article: string; passage: string };
export type BibleChapter = {
  n: number; verses: number; ranges: [number, number][]; sermons: BibleSermonRef[];
};
export type BibleBook = {
  num: number; name: string; chapters: BibleChapter[];
  covered_chapters: number; total_chapters: number;
};
export async function bibleCoverage(): Promise<{ books: BibleBook[] }> {
  const r = await fetch("/bible/coverage", { headers: HDRS });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
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
  learning_recall_enabled: boolean;
  codex_sandbox: "read-only" | "workspace-write";
  claude_permission_mode: "default" | "acceptEdits";
  workspace_dir: string | null;
  output_dir: string | null;
  font_body: string;
  font_heading: string;
};
export type WorkspaceInfo = {
  workspace_dir: string | null; exists: boolean | null;
  skills: string[]; has_claude_md: boolean;
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
export async function workspaceInfo(): Promise<WorkspaceInfo> {
  return (await fetch("/workspace/info", { headers: HDRS })).json();
}

export type SetupStatus = {
  cli: CliStatus;
  workspace_dir: string | null;
  workspace_ready: boolean;
  all_ready: boolean;
};

export async function setupStatus(): Promise<SetupStatus> {
  const r = await fetch("/setup/status", { headers: HDRS });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
export async function installCli(): Promise<{ ok: boolean; tail?: string; hint?: string }> {
  const r = await fetch("/setup/install-cli", { method: "POST", headers: HDRS });
  return r.json();
}
export async function openLogin(): Promise<{ ok: boolean; error?: string }> {
  const r = await fetch("/setup/open-login", { method: "POST", headers: HDRS });
  return r.json();
}
export async function installWorkspace(): Promise<{ workspace_dir: string; skills: number }> {
  const r = await fetch("/setup/install-workspace", { method: "POST", headers: HDRS });
  if (!r.ok) throw new Error((await r.json()).error ?? `HTTP ${r.status}`);
  return r.json();
}

export type WorkspaceUpdateStatus = {
  available: boolean;
  changed: string[];
  added: string[];
  reason: "no_bundle" | "no_workspace" | "git" | null;
};

export async function workspaceUpdateStatus(): Promise<WorkspaceUpdateStatus> {
  const r = await fetch("/setup/workspace-update", { headers: HDRS });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
export async function updateWorkspace(): Promise<{ updated: string[]; backup_dir: string | null }> {
  const r = await fetch("/setup/update-workspace", { method: "POST", headers: HDRS });
  if (!r.ok) throw new Error((await r.json()).error ?? `HTTP ${r.status}`);
  return r.json();
}

export type Rule = { id: number; rule: string; active: boolean; pending: boolean; created_at: string };

export async function getRules(): Promise<{ rules: Rule[]; undistilled: number }> {
  return (await fetch("/rules", { headers: HDRS })).json();
}
export async function setRuleActive(id: number, active: boolean): Promise<void> {
  await fetch("/rules", { method: "POST", headers: HDRS, body: JSON.stringify({ id, active }) });
}
export async function runDistill(): Promise<{ added: string[]; candidates?: string[]; error?: string; skipped?: string }> {
  const r = await fetch("/distill", { method: "POST", headers: HDRS });
  const j = await r.json();
  if (!r.ok) throw new Error(j.error ?? `HTTP ${r.status}`);
  return j;
}

export type DocumentSaveResult = {
  changed: boolean;
  path: string;
  version_path: string | null;
  additions: number;
  deletions: number;
  learned: boolean;
  promoted?: {
    approved: number;
    historical?: number;
    profile_path: string | null;
    theology_path: string | null;
    pattern_path?: string | null;
  } | null;
};

export async function saveWorkspaceDocument(
  path: string,
  content: string,
  messageId?: number,
): Promise<DocumentSaveResult> {
  const r = await fetch("/workspace-file", {
    method: "PUT",
    headers: HDRS,
    body: JSON.stringify({ path, content, message_id: messageId }),
  });
  const payload = await r.json();
  if (!r.ok) throw new Error(payload.error ?? `HTTP ${r.status}`);
  return payload;
}

export type ReviewSummary = {
  path: string;
  title: string;
  status: "in_review" | "reviewed";
  total: number;
  decided: number;
  updated_at?: string | null;
};

export async function listReviews(): Promise<ReviewSummary[]> {
  const r = await fetch("/reviews", { headers: HDRS });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return (await r.json()).reviews;
}

export type PresentationJob = {
  id: string; title: string; source_name: string;
  status: "queued" | "running" | "completed" | "failed";
  stage: string; progress: number; provider: "codex" | "claude";
  created_at: string; updated_at: string; log: string[];
  result?: string | null; error?: string | null;
  options?: { style_preset?: string; image_style?: string; tone?: string; slide_count?: number };
};
export type PresentationEngines = {
  ppt_master: { available: boolean; path: string | null };
  codex_fleet: { available: boolean; path: string | null };
  prompt_kit: { available: boolean; path: string | null };
  worker: { available: boolean; state?: "idle" | "working" | "stopped"; job_id?: string | null };
  styles: { id: string; name: string; description: string; tone: string }[];
  default_style: string;
  image_styles: { id: string; name: string; description: string }[];
  default_image_style: string;
};

export async function presentationEngines(): Promise<PresentationEngines> {
  const r = await fetch("/presentations/engines", { headers: HDRS });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
export async function listPresentations(): Promise<PresentationJob[]> {
  const r = await fetch("/presentations", { headers: HDRS });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return (await r.json()).jobs;
}
export async function createPresentation(
  file: File,
  options: {
    title: string; audience: string; slide_count: number; aspect: "16:9" | "4:3";
    tone: string; provider: "codex" | "claude"; use_ai_images: boolean;
    speaker_notes: boolean; style_preset: string; image_style: string;
  },
): Promise<PresentationJob> {
  const form = new FormData();
  form.append("file", file, file.name);
  Object.entries(options).forEach(([key, value]) => form.append(key, String(value)));
  const r = await fetch("/presentations", {
    method: "POST", headers: { "Authorization": `Bearer ${TOKEN}` }, body: form,
  });
  const payload = await r.json();
  if (!r.ok) throw new Error(payload.error ?? `HTTP ${r.status}`);
  return payload;
}
export function downloadPresentation(job: PresentationJob): void {
  const params = new URLSearchParams({ token: TOKEN });
  const a = document.createElement("a");
  a.href = `/presentations/${job.id}/download?${params.toString()}`;
  a.download = `${job.title || "presentation"}.pptx`;
  a.style.display = "none";
  document.body.appendChild(a);
  a.click();
  a.remove();
}
export async function openPresentation(
  job: PresentationJob, reveal = false,
): Promise<{ ok: boolean; path: string }> {
  const action = reveal ? "reveal" : "open";
  const r = await fetch(`/presentations/${job.id}/${action}`, {
    method: "POST", headers: HDRS, body: "{}",
  });
  const payload = await r.json();
  if (!r.ok) throw new Error(payload.error ?? `HTTP ${r.status}`);
  return payload;
}
export async function retryPresentation(id: string): Promise<PresentationJob> {
  const r = await fetch(`/presentations/${id}/retry`, {
    method: "POST", headers: HDRS, body: "{}",
  });
  const payload = await r.json();
  if (!r.ok) throw new Error(payload.error ?? `HTTP ${r.status}`);
  return payload;
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


export type LearningItem = {
  name: string; title: string; chars: number; preview: string;
  status: "ok" | "empty" | "duplicate" | "error"; reason: string; duplicate_of: string;
};
export type LearningJob = {
  id: string; status: "queued" | "absorbing" | "profiling" | "completed" | "failed";
  stage: string; batch_id: string; source_ids: string[]; primary: number; reference: number;
  log: string[]; error: string | null; created_at: string; updated_at: string;
};
export type LearningStatus = {
  ready: boolean; reason: "no_workspace" | "no_config" | null;
  workspace_dir: string | null; jobs: LearningJob[];
};

export async function learningStatus(): Promise<LearningStatus> {
  const r = await fetch("/learning/status", { headers: HDRS });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
export async function uploadManuscripts(files: File[]): Promise<{ upload_id: string; items: LearningItem[] }> {
  const form = new FormData();
  files.forEach(f => form.append("files", f, f.name));
  const r = await fetch("/learning/uploads", {
    method: "POST", headers: { Authorization: HDRS.Authorization }, body: form });
  if (!r.ok) throw new Error((await r.json()).error ?? `HTTP ${r.status}`);
  return r.json();
}
export async function startLearning(
  uploadId: string,
  items: { name: string; title: string; type: "primary" | "reference"; include: boolean }[],
): Promise<LearningJob> {
  const r = await fetch("/learning/jobs", {
    method: "POST", headers: HDRS, body: JSON.stringify({ upload_id: uploadId, items }) });
  if (!r.ok) throw new Error((await r.json()).error ?? `HTTP ${r.status}`);
  return r.json();
}
export async function retryLearning(id: string): Promise<LearningJob> {
  const r = await fetch(`/learning/jobs/${id}/retry`, { method: "POST", headers: HDRS });
  if (!r.ok) throw new Error((await r.json()).error ?? `HTTP ${r.status}`);
  return r.json();
}
export async function discardUpload(id: string): Promise<void> {
  await fetch(`/learning/uploads/${id}`, { method: "DELETE", headers: HDRS });
}
