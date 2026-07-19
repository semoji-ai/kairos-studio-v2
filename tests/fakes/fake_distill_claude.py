"""claude CLI 흉내: 증류 결과(JSON 배열 or 비-JSON 프로즈)를 stream-json으로 뱉는다.
env FAKE_BAD=1 이면 파싱 불가능한 프로즈를 result로 낸다 (파싱 실패 테스트용).
"""
import json
import os
import sys

out = sys.stdout


def emit(obj):
    out.write(json.dumps(obj) + "\n")
    out.flush()


emit({"type": "system", "subtype": "init", "session_id": "sess-distill",
      "model": "claude-fable-5"})

if os.environ.get("FAKE_BAD") == "1":
    result_text = "말로 설명하자면 규칙을 추출하기 어렵습니다. JSON을 못 만들겠어요."
else:
    result_text = json.dumps(
        [{"rule": "가운뎃점 대신 쉼표를 쓴다", "source_ids": [1]}],
        ensure_ascii=False,
    )

emit({"type": "stream_event",
      "event": {"type": "content_block_delta",
                "delta": {"type": "text_delta", "text": result_text}}})
emit({"type": "result", "subtype": "success",
      "result": result_text, "session_id": "sess-distill"})
