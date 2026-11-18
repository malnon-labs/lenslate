"""A stand-in for ocr_server.py / mt_server.py that misbehaves on purpose (FAKE_MODE): noise, hang or crash."""
import json
import os
import sys
import time

mode = os.environ.get("FAKE_MODE", "noise")
print("a library banner on stdout before the ready line", flush=True)
print(json.dumps({"ready": True}), flush=True)
for line in sys.stdin:
    req = json.loads(line)
    if mode == "noise":
        print("WARNING: some library chatter", flush=True)
        print(json.dumps({"lines": ["stale"], "id": -5}), flush=True)          # an answer to another request
        print(json.dumps({"lines": [req["path"]], "secs": 0, "id": req["id"]}), flush=True)
    elif mode == "hang":
        time.sleep(1000)
    elif mode == "crash":
        os._exit(1)
