import { useEffect, useState } from "react";
import Chat from "./Chat";
import Setup from "./Setup";
import { getSettings, setupStatus } from "./api";
import { applyFonts } from "./fonts";

export default function App() {
  const [ready, setReady] = useState<boolean | null>(null);

  useEffect(() => {
    // 저장된 글꼴 적용 — 실패해도 시스템 글꼴로 그대로 동작한다
    getSettings().then(s => applyFonts(s.font_body, s.font_heading)).catch(() => undefined);
    setupStatus()
      .then(s => setReady(s.all_ready))
      .catch(() => setReady(true)); // 사이드카가 setup 라우트를 지원하지 않거나 실패하면 채팅으로 폴백
  }, []);

  if (ready === null) return null;
  if (!ready) return <Setup onDone={() => setReady(true)} />;
  return <Chat />;
}
