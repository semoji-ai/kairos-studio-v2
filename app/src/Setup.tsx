import { useEffect, useState } from "react";
import { installCli, installWorkspace, openLogin, putSettings, setupStatus } from "./api";
import type { SetupStatus } from "./api";

const card: React.CSSProperties = { border: "1px solid #ddd", borderRadius: 8, padding: 16, marginBottom: 16 };

export default function Setup({ onDone }: { onDone: () => void }) {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [installing, setInstalling] = useState(false);
  const [installResult, setInstallResult] = useState<{ ok: boolean; tail?: string } | null>(null);
  const [checking, setChecking] = useState(false);
  const [wsInstalling, setWsInstalling] = useState(false);
  const [wsResult, setWsResult] = useState<{ workspace_dir: string; skills: number } | null>(null);
  const [wsError, setWsError] = useState<string | null>(null);
  const [permBumped, setPermBumped] = useState(false);

  function refresh() {
    return setupStatus().then(setStatus);
  }

  useEffect(() => { refresh(); }, []);

  async function doInstallCli() {
    setInstalling(true); setInstallResult(null);
    try {
      const res = await installCli();
      setInstallResult(res);
    } finally {
      setInstalling(false);
      await refresh();
    }
  }

  async function doOpenLogin() {
    await openLogin();
  }

  async function doCheck() {
    setChecking(true);
    try { await refresh(); } finally { setChecking(false); }
  }

  async function doInstallWorkspace() {
    setWsInstalling(true); setWsError(null); setWsResult(null);
    try {
      const res = await installWorkspace();
      setWsResult(res);
      await refresh();
    } catch (e) {
      setWsError(e instanceof Error ? e.message : String(e));
    } finally {
      setWsInstalling(false);
    }
  }

  async function bumpPermission() {
    await putSettings({ claude_permission_mode: "acceptEdits" });
    setPermBumped(true);
  }

  const claude = status?.cli?.claude;
  const installed = !!claude?.installed;
  const authed = !!claude?.authed;

  return (
    <main style={{ flex: 1, display: "flex", flexDirection: "column", overflowY: "auto", padding: 24, fontFamily: "sans-serif", maxWidth: 640, margin: "0 auto" }}>
      <h2>카이로스 스튜디오 첫 실행 설정</h2>

      <section style={card}>
        <h3>① Claude 설치 {installed && "✅"}</h3>
        {installed ? (
          <p>설치되어 있습니다{claude?.version ? ` (${claude.version})` : ""}.</p>
        ) : (
          <>
            <button disabled={installing} onClick={doInstallCli}>
              {installing ? "설치 중..." : "설치하기"}
            </button>
            {installResult && (
              <div style={{ marginTop: 8 }}>
                {installResult.ok ? (
                  <span>설치 완료</span>
                ) : (
                  <div style={{ background: "#fee2e2", color: "#991b1b", padding: 8, borderRadius: 4, fontSize: 12 }}>
                    설치 실패. 수동 설치가 필요할 수 있습니다.
                    {installResult.tail && <pre style={{ whiteSpace: "pre-wrap" }}>{installResult.tail}</pre>}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </section>

      <section style={card}>
        <h3>② 로그인 {authed && "✅"}</h3>
        {authed ? (
          <p>로그인되어 있습니다.</p>
        ) : (
          <>
            <button onClick={doOpenLogin} disabled={!installed}>로그인 터미널 열기</button>
            <button style={{ marginLeft: 8 }} disabled={checking} onClick={doCheck}>
              {checking ? "확인 중..." : "다시 확인"}
            </button>
          </>
        )}
      </section>

      <section style={card}>
        <h3>③ 설교 도우미 (선택) {status?.workspace_ready && "✅"}</h3>
        {status?.workspace_ready ? (
          <p>스킬 사용 가능. 작업 폴더: {status.workspace_dir}</p>
        ) : (
          <>
            <button disabled={wsInstalling} onClick={doInstallWorkspace}>
              {wsInstalling ? "설치 중..." : "설치"}
            </button>
            {wsError && (
              <div style={{ background: "#fee2e2", color: "#991b1b", padding: 8, borderRadius: 4, marginTop: 8, fontSize: 12 }}>
                {wsError}
              </div>
            )}
          </>
        )}
        {wsResult && (
          <div style={{ marginTop: 8 }}>
            <div>스킬 {wsResult.skills}개 설치됨.</div>
            <div style={{ fontSize: 12, marginTop: 4 }}>
              스킬이 파일을 쓰려면 권한을 acceptEdits로 올리는 것을 권장합니다.
              {" "}
              <button disabled={permBumped} onClick={bumpPermission}>
                {permBumped ? "권한 상향됨" : "권한 올리기"}
              </button>
            </div>
          </div>
        )}
      </section>

      <button disabled={!status?.all_ready} onClick={onDone} style={{ padding: "8px 24px", fontWeight: "bold" }}>
        시작하기
      </button>
    </main>
  );
}
