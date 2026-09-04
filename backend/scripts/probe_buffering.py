"""Confirm the `buffering` frames actually reach a client during a long window."""
import json, sys, time, wave
import requests
from websockets.sync.client import connect

base = "http://127.0.0.1:19844"
with wave.open("/tmp/claude-0/-root/2257e947-aa0a-4678-81b2-5bb386c8707f/scratchpad/eval16k/kaferoon.wav") as w:
    pcm = w.readframes(w.getnframes())[: 16000 * 2 * 12]      # first 12s only

sid = requests.post(f"{base}/api/sessions", json={"surah_id": 109, "start_ayah": 1},
                    timeout=10).json()["session_id"]
frames, first_at, last_sec = [], None, None
t0 = time.perf_counter()
with connect(base.replace("http://", "ws://") + f"/ws/session/{sid}", open_timeout=20) as ws:
    for i in range(0, len(pcm), 3200):
        ws.send(pcm[i:i + 3200])
        target = t0 + (i + 3200) / 2 / 16000 / 1.05
        while (slack := target - time.perf_counter()) > 0:
            try:
                m = json.loads(ws.recv(timeout=slack))
            except TimeoutError:
                break
            if m.get("type") == "buffering":
                frames.append(m)
                if first_at is None:
                    first_at = round(time.perf_counter() - t0, 1)
                last_sec = m["buffered_sec"]
requests.post(f"{base}/api/sessions/{sid}/end", timeout=30)

print(f"buffering frames: {len(frames)}  first at {first_at}s  last buffered_sec={last_sec}")
print(f"sample: {frames[:2]}")
ok = len(frames) >= 5 and first_at is not None and first_at < 6
print("PROBE " + ("PASS — the UI has a heartbeat during a long window" if ok
                  else "FAIL — no heartbeat reaches the client"))
sys.exit(0 if ok else 1)
