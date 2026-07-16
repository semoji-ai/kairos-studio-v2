import json
import sys


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


resumed = "resume" in sys.argv
emit({"type": "thread.started", "thread_id": "th-123"})
emit({"type": "item.completed",
      "item": {"id": "item_0", "type": "agent_message",
               "text": ("[resumed]" if resumed else "") + "코드 확인 완료"}})
emit({"type": "turn.completed", "usage": {"input_tokens": 10}})
