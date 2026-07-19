"""claude CLI 흉내: -p 뒤 프롬프트 텍스트를 그대로 result로 에코한다.

테스트에서 응답 텍스트에 파일 경로를 실어보내기 위한 fake. stream-json 이벤트
모양은 fake_claude.py와 동일하게 유지한다.
"""
import json
import sys

out = sys.stdout


def emit(obj):
    out.write(json.dumps(obj) + "\n")
    out.flush()


prompt = sys.argv[sys.argv.index("-p") + 1] if "-p" in sys.argv else ""

emit({"type": "system", "subtype": "init", "session_id": "sess-echo",
      "model": "claude-fable-5"})
emit({"type": "stream_event",
      "event": {"type": "content_block_delta",
                "delta": {"type": "text_delta", "text": prompt}}})
emit({"type": "result", "subtype": "success", "result": prompt,
      "session_id": "sess-echo"})
