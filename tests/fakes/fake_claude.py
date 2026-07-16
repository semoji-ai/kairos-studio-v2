"""claude CLI 흉내: stream-json 이벤트를 stdout에 뱉는다."""
import json
import sys

out = sys.stdout


def emit(obj):
    out.write(json.dumps(obj) + "\n")
    out.flush()


# 인자에 --resume 이 있으면 session_ref 전달 검증용 마커를 응답에 포함
resumed = "--resume" in sys.argv
prompt = sys.argv[sys.argv.index("-p") + 1] if "-p" in sys.argv else ""

emit({"type": "system", "subtype": "init", "session_id": "sess-abc",
      "model": "claude-fable-5"})
for chunk in ["안녕", "하세요"]:
    emit({"type": "stream_event",
          "event": {"type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": chunk}}})
emit({"type": "result", "subtype": "success",
      "result": ("[resumed]" if resumed else "") + "안녕하세요",
      "session_id": "sess-abc"})
