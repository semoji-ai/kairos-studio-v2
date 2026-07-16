import { useEffect, useState } from "react";
import { cliStatus, getSettings, putSettings, storageInfo } from "./api";
import type { CliStatus, Settings as SettingsType, StorageInfo } from "./api";

function badge(installed: boolean, authed: boolean | null): string {
  if (!installed) return "❌";
  if (authed === null) return "확인 불가";
  return authed ? "✅" : "❌";
}

export default function Settings({ onClose }: { onClose: () => void }) {
  const [settings, setSettings] = useState<SettingsType | null>(null);
  const [cli, setCli] = useState<CliStatus | null>(null);
  const [storage, setStorage] = useState<StorageInfo | null>(null);
  const [dataDirInput, setDataDirInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getSettings().then(s => { setSettings(s); setDataDirInput(s.data_dir); });
    cliStatus().then(setCli);
    storageInfo().then(setStorage);
  }, []);

  async function save(patch: Partial<SettingsType>) {
    setSaving(true); setError(null);
    try {
      const updated = await putSettings(patch);
      setSettings(updated);
      const s = await storageInfo();
      setStorage(s);
      setDataDirInput(updated.data_dir);
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
    <main style={{ flex: 1, display: "flex", flexDirection: "column", overflowY: "auto", padding: 16, fontFamily: "sans-serif" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2>설정</h2>
        <button onClick={onClose}>닫기</button>
      </div>

      {error && (
        <div style={{ background: "#fee2e2", color: "#991b1b", padding: 8, borderRadius: 4, margin: "8px 0" }}>
          {error}
        </div>
      )}

      <section style={{ margin: "16px 0" }}>
        <h3>CLI 상태</h3>
        {cli == null ? <p>불러오는 중...</p> : (
          <div style={{ display: "flex", gap: 12 }}>
            {Object.entries(cli).map(([name, st]) => (
              <div key={name} style={{ border: "1px solid #ddd", borderRadius: 8, padding: 12, minWidth: 200 }}>
                <div style={{ fontWeight: "bold" }}>{name}</div>
                <div>설치: {st.installed ? "✅" : "❌"}</div>
                <div>버전: {st.version ?? "-"}</div>
                <div>로그인: {badge(st.installed, st.authed)}</div>
                {st.authed === false && st.login_hint && (
                  <div style={{ marginTop: 4, fontSize: 12 }}>
                    <code>{st.login_hint}</code>
                    <button style={{ marginLeft: 4 }} onClick={() => copy(st.login_hint)}>복사</button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      <section style={{ margin: "16px 0" }}>
        <h3>저장소</h3>
        {storage?.fallback && (
          <div style={{ background: "#fef3c7", color: "#92400e", padding: 8, borderRadius: 4, marginBottom: 8 }}>
            경로를 열 수 없어 로컬 기본 경로로 폴백했습니다.
          </div>
        )}
        <div>현재 경로: {storage?.data_dir ?? "-"}</div>
        <div>DB 용량: {storage ? (storage.db_bytes / 1048576).toFixed(1) : "-"} MB</div>
        <div style={{ marginTop: 8 }}>
          <input value={dataDirInput} onChange={e => setDataDirInput(e.target.value)}
                 style={{ width: 300 }} />
          <button style={{ marginLeft: 8 }} disabled={saving}
                  onClick={() => save({ data_dir: dataDirInput })}>저장</button>
        </div>
      </section>

      <section style={{ margin: "16px 0" }}>
        <h3>라우팅·권한</h3>
        {settings && (
          <>
            <div>
              기본 provider:
              <label style={{ marginLeft: 8 }}>
                <input type="radio" name="default_provider" checked={settings.default_provider === "claude"}
                       onChange={() => save({ default_provider: "claude" })} /> claude
              </label>
              <label style={{ marginLeft: 8 }}>
                <input type="radio" name="default_provider" checked={settings.default_provider === "codex"}
                       onChange={() => save({ default_provider: "codex" })} /> codex
              </label>
            </div>
            <div style={{ marginTop: 8 }}>
              <label>
                <input type="checkbox" checked={settings.routing_rules_enabled}
                       onChange={e => save({ routing_rules_enabled: e.target.checked })} />
                {" "}라우팅 규칙 사용
              </label>
            </div>
            <div style={{ marginTop: 8 }}>
              codex sandbox:
              <select style={{ marginLeft: 8 }} value={settings.codex_sandbox}
                      onChange={e => save({ codex_sandbox: e.target.value as SettingsType["codex_sandbox"] })}>
                <option value="read-only">read-only</option>
                <option value="workspace-write">workspace-write</option>
              </select>
            </div>
            <div style={{ marginTop: 8 }}>
              claude permission mode:
              <select style={{ marginLeft: 8 }} value={settings.claude_permission_mode}
                      onChange={e => save({ claude_permission_mode: e.target.value as SettingsType["claude_permission_mode"] })}>
                <option value="default">default</option>
                <option value="acceptEdits">acceptEdits</option>
              </select>
            </div>
          </>
        )}
      </section>
    </main>
  );
}
