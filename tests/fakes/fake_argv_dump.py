"""받은 argv를 그대로 보고하는 fake — 플래그 반영 검증용. 최소 유효 이벤트도 뱉는다."""
import json
import sys

def emit(o):
    sys.stdout.write(json.dumps(o, ensure_ascii=False) + "\n")

argv = sys.argv[1:]
if "exec" in argv:  # codex 모드
    emit({"type": "thread.started", "thread_id": "t"})
    emit({"type": "item.completed",
          "item": {"type": "agent_message", "text": json.dumps(argv, ensure_ascii=False)}})
else:  # claude 모드
    emit({"type": "system", "subtype": "init", "session_id": "s", "model": "m"})
    emit({"type": "result", "subtype": "success",
          "result": json.dumps(argv, ensure_ascii=False), "session_id": "s"})
