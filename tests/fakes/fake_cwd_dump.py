"""현재 작업 디렉토리를 결과로 보고하는 fake."""
import json
import os
import sys

def emit(o):
    sys.stdout.write(json.dumps(o) + "\n")

emit({"type": "system", "subtype": "init", "session_id": "s", "model": "m"})
emit({"type": "result", "subtype": "success", "result": os.getcwd(),
      "session_id": "s"})
