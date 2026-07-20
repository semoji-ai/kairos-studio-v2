import json
import sys


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


if "app-server" in sys.argv:
    resumed = False
    for line in sys.stdin:
        msg = json.loads(line)
        if msg.get("id") == 0:
            emit({"id": 0, "result": {"userAgent": "fake"}})
        elif msg.get("id") == 1:
            resumed = msg.get("method") == "thread/resume"
            emit({"id": 1, "result": {"thread": {"id": "th-123"}}})
        elif msg.get("id") == 2:
            emit({"method": "item/started", "params": {"item": {
                "id": "log-1", "type": "agentMessage", "phase": "commentary"}}})
            emit({"method": "item/agentMessage/delta", "params": {
                "itemId": "log-1", "delta": "checking sources"}})
            emit({"method": "item/completed", "params": {"item": {
                "id": "log-1", "type": "agentMessage", "phase": "commentary",
                "text": "checking sources"}}})
            text = ("[resumed]" if resumed else "") + "肄붾뱶 ?뺤씤 ?꾨즺"
            emit({"method": "item/started", "params": {"item": {
                "id": "item-1", "type": "agentMessage", "phase": "final_answer"}}})
            middle = max(1, len(text) // 2)
            for delta in (text[:middle], text[middle:]):
                emit({"method": "item/agentMessage/delta", "params": {
                    "threadId": "th-123", "turnId": "turn-1",
                    "itemId": "item-1", "delta": delta}})
            emit({"method": "item/completed", "params": {"item": {
                "id": "item-1", "type": "agentMessage", "phase": "final_answer",
                "text": text}}})
            emit({"method": "turn/completed", "params": {
                "threadId": "th-123",
                "turn": {"id": "turn-1", "status": "completed"}}})
            break
else:
    resumed = "resume" in sys.argv
    emit({"type": "thread.started", "thread_id": "th-123"})
    emit({"type": "item.completed", "item": {
        "id": "item_0", "type": "agent_message",
        "text": ("[resumed]" if resumed else "") + "肄붾뱶 ?뺤씤 ?꾨즺"}})
    emit({"type": "turn.completed", "usage": {"input_tokens": 10}})
