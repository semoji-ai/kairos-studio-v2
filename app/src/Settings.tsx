import { useEffect, useState } from "react";
import { cliStatus, getRules, getSettings, putSettings, runDistill, setRuleActive, storageInfo, workspaceInfo } from "./api";
import type { CliStatus, Rule, Settings as SettingsType, StorageInfo, WorkspaceInfo } from "./api";

function badge(installed: boolean, authed: boolean | null): string {
  if (!installed) return "❌";
  if (authed === null) return "확인 불가";
  return authed ? "✅" : "❌";
}

export default function Settings({ onClose }: { onClose: () => void }) {
  const [settings, setSettings] = useState<SettingsType | null>(null);
  const [cli, setCli] = useState<CliStatus | null>(null);
  const [storage, setStorage] = useState<StorageInfo | null>(null);
  const [workspace, setWorkspace] = useState<WorkspaceInfo | null>(null);
  const [dataDirInput, setDataDirInput] = useState("");
  const [workspaceDirInput, setWorkspaceDirInput] = useState("");
  const [outputDirInput, setOutputDirInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [rules, setRules] = useState<Rule[]>([]);
  const [undistilled, setUndistilled] = useState(0);
  const [distilling, setDistilling] = useState(false);
  const [distillResult, setDistillResult] = useState<string | null>(null);
  const [distillError, setDistillError] = useState<string | null>(null);

  function refreshRules() {
    getRules().then(r => { setRules(r.rules); setUndistilled(r.undistilled); });
  }

  useEffect(() => {
    getSettings().then(s => {
      setSettings(s);
      setDataDirInput(s.data_dir);
      setWorkspaceDirInput(s.workspace_dir ?? "");
      setOutputDirInput(s.output_dir ?? "");
    });
    cliStatus().then(setCli);
    storageInfo().then(setStorage);
    workspaceInfo().then(setWorkspace);
    refreshRules();
  }, []);

  async function doDistill() {
    setDistilling(true); setDistillResult(null); setDistillError(null);
    try {
      const res = await runDistill();
      if (res.error) {
        setDistillError(res.error);
      } else {
        setDistillResult(`규칙 ${res.added.length}개 추가`);
      }
      refreshRules();
    } catch (e) {
      setDistillError(e instanceof Error ? e.message : String(e));
    } finally {
      setDistilling(false);
    }
  }

  async function toggleRule(id: number, active: boolean) {
    try {
      await setRuleActive(id, active);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      refreshRules();
    }
  }

  async function save(patch: Partial<SettingsType>) {
    setSaving(true); setError(null);
    try {
      const updated = await putSettings(patch);
      setSettings(updated);
      const s = await storageInfo();
      setStorage(s);
      setDataDirInput(updated.data_dir);
      setWorkspaceDirInput(updated.workspace_dir ?? "");
      setOutputDirInput(updated.output_dir ?? "");
      const w = await workspaceInfo();
      setWorkspace(w);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  function copy(text: string) {
    navigator.clipboard.writeText(text);
  }

  return (
    <main className="page">
      <div className="page-inner">
      <header className="page-header">
        <div>
          <span className="page-eyebrow">SETTINGS</span>
          <h1>설정</h1>
        </div>
        <button onClick={onClose}>닫기</button>
      </header>

      {error && <div className="notice error" style={{ marginBottom: 16 }}>{error}</div>}

      <section className="card">
        <h3>CLI 상태</h3>
        {cli == null ? <p className="hint">불러오는 중...</p> : (
          <div className="cli-grid">
            {Object.entries(cli).map(([name, st]) => (
              <div key={name} className="cli-card">
                <strong>{name}</strong>
                <dl className="kv">
                  <dt>설치</dt><dd>{st.installed ? "✅" : "❌"}</dd>
                  <dt>버전</dt><dd>{st.version ?? "-"}</dd>
                  <dt>로그인</dt><dd>{badge(st.installed, st.authed)}</dd>
                </dl>
                {st.authed === false && st.login_hint && (
                  <div className="field-row" style={{ marginTop: 8, fontSize: 12 }}>
                    <code>{st.login_hint}</code>
                    <button onClick={() => copy(st.login_hint)}>복사</button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="card">
        <h3>저장소</h3>
        {storage?.fallback && (
          <div className="notice warn" style={{ marginBottom: 12 }}>
            경로를 열 수 없어 로컬 기본 경로로 폴백했습니다.
          </div>
        )}
        <dl className="kv">
          <dt>현재 경로</dt><dd>{storage?.data_dir ?? "-"}</dd>
          <dt>DB 용량</dt><dd>{storage ? (storage.db_bytes / 1048576).toFixed(1) : "-"} MB</dd>
        </dl>
        <div className="field">
          <div className="field-row">
            <input value={dataDirInput} onChange={e => setDataDirInput(e.target.value)} />
            <button disabled={saving}
                    onClick={() => save({ data_dir: dataDirInput })}>저장</button>
          </div>
        </div>

        <div className="field" style={{ marginTop: 20 }}>
          <span className="field-label">작업 폴더</span>
          <div className="field-row">
            <input value={workspaceDirInput} onChange={e => setWorkspaceDirInput(e.target.value)}
                   placeholder="(미설정)" />
            <button disabled={saving}
                    onClick={() => save({ workspace_dir: workspaceDirInput.trim() === "" ? null : workspaceDirInput })}>저장</button>
          </div>
          {workspace && workspace.skills.length > 0 && (
            <div className="hint">
              스킬 {workspace.skills.length}개 감지: {workspace.skills.slice(0, 8).join(", ")}
              {workspace.skills.length > 8 ? "…" : ""}
            </div>
          )}
          {workspace?.workspace_dir && settings?.claude_permission_mode === "default" && (
            <div className="notice warn">
              스킬이 파일을 쓰려면 권한을 acceptEdits / workspace-write로 올리는 것을 권장합니다
            </div>
          )}
        </div>

        <div className="field" style={{ marginTop: 20 }}>
          <span className="field-label">산출물 폴더</span>
          <div className="hint">
            작업 폴더의 지침·도구는 유지하고, 완성된 문서와 이미지만 세션별로 모읍니다.
          </div>
          <div className="field-row">
            <input value={outputDirInput} onChange={e => setOutputDirInput(e.target.value)}
                   placeholder="(미설정)" />
            <button disabled={saving}
                    onClick={() => save({ output_dir: outputDirInput.trim() === "" ? null : outputDirInput })}>
              저장
            </button>
          </div>
        </div>
      </section>

      <section className="card">
        <h3>라우팅·권한</h3>
        {settings && (
          <div className="stack">
            <div className="field-row">
              <span className="field-label" style={{ minWidth: 150 }}>기본 provider</span>
              <div className="check-group">
                <label className="check">
                  <input type="radio" name="default_provider" checked={settings.default_provider === "claude"}
                         onChange={() => save({ default_provider: "claude" })} /> claude
                </label>
                <label className="check">
                  <input type="radio" name="default_provider" checked={settings.default_provider === "codex"}
                         onChange={() => save({ default_provider: "codex" })} /> codex
                </label>
              </div>
            </div>
            <label className="check">
              <input type="checkbox" checked={settings.routing_rules_enabled}
                     onChange={e => save({ routing_rules_enabled: e.target.checked })} />
              라우팅 규칙 사용
            </label>
            <label className="check">
              <input type="checkbox" checked={settings.learning_recall_enabled}
                     onChange={e => save({ learning_recall_enabled: e.target.checked })} />
              학습 회상 (과거 대화 자동 참조)
            </label>
            <div className="field-row">
              <span className="field-label" style={{ minWidth: 150 }}>codex sandbox</span>
              <select value={settings.codex_sandbox}
                      onChange={e => save({ codex_sandbox: e.target.value as SettingsType["codex_sandbox"] })}>
                <option value="read-only">read-only</option>
                <option value="workspace-write">workspace-write</option>
              </select>
            </div>
            <div className="field-row">
              <span className="field-label" style={{ minWidth: 150 }}>claude permission mode</span>
              <select value={settings.claude_permission_mode}
                      onChange={e => save({ claude_permission_mode: e.target.value as SettingsType["claude_permission_mode"] })}>
                <option value="default">default</option>
                <option value="acceptEdits">acceptEdits</option>
              </select>
            </div>
          </div>
        )}
      </section>

      <section className="card">
        <h3>학습된 규칙</h3>
        <div className="field-row">
          <span className="hint">미증류 피드백 {undistilled}건</span>
          <button className="btn-primary" disabled={distilling} onClick={doDistill}>
            {distilling ? "증류 중..." : "지금 증류"}
          </button>
          {distillResult && <span className="status-ok">{distillResult}</span>}
          {distillError && <span className="status-bad">{distillError}</span>}
        </div>
        <ul className="rule-list">
          {rules.map(r => (
            <li key={r.id}>
              <label className="check">
                <input type="checkbox" checked={!!r.active}
                       onChange={e => toggleRule(r.id, e.target.checked)} />
                {r.rule}
              </label>
            </li>
          ))}
        </ul>
      </section>
      </div>
    </main>
  );
}
