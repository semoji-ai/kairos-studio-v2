import { useEffect, useState } from "react";
import Chat from "./Chat";
import Setup from "./Setup";
import { setupStatus } from "./api";

export default function App() {
  const [ready, setReady] = useState<boolean | null>(null);

  useEffect(() => {
    setupStatus()
      .then(s => setReady(s.all_ready))
      .catch(() => setReady(true)); // 사이드카가 setup 라우트를 지원하지 않거나 실패하면 채팅으로 폴백
  }, []);

  if (ready === null) return null;
  if (!ready) return <Setup onDone={() => setReady(true)} />;
  return <Chat />;
}
