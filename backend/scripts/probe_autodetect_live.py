"""Measure real auto-detect latency against a running server.

Reports the wall-clock time from first audio byte to the `detected` frame — the
number the reciter actually experiences, which was 30-40 s before detection
stopped waiting for a tracking window.

usage: probe_autodetect_live.py <base_url> <wav> [expected_surah]
"""
import json
import sys
import time
import wave

import requests
from websockets.sync.client import connect

BASE, WAV = sys.argv[1], sys.argv[2]
EXPECT = int(sys.argv[3]) if len(sys.argv) > 3 else None

with wave.open(WAV) as w:
    pcm = w.readframes(w.getnframes())

sid = requests.post(f"{BASE}/api/sessions", json={"auto": True}, timeout=15).json()["session_id"]
ws_url = BASE.replace("https://", "wss://").replace("http://", "ws://")

detected_at, detected = None, None
t0 = time.perf_counter()
with connect(f"{ws_url}/ws/session/{sid}", open_timeout=30, max_size=None) as ws:
    for i in range(0, len(pcm), 3200):
        ws.send(pcm[i:i + 3200])
        target = t0 + (i + 3200) / 2 / 16000 / 1.05
        while (slack := target - time.perf_counter()) > 0:
            try:
                m = json.loads(ws.recv(timeout=slack))
            except TimeoutError:
                break
            if m.get("type") == "detected" and detected_at is None:
                detected_at = time.perf_counter() - t0
                detected = (m["surah"], m["ayah"], m.get("score"))
        if detected_at is not None:
            break            # that is the number we came for
    try:
        ws.send(json.dumps({"type": "end"}))
    except Exception:
        pass
requests.post(f"{BASE}/api/sessions/{sid}/end", timeout=30)

if detected_at is None:
    print(f"NO LOCK within {time.perf_counter() - t0:.1f}s of audio")
    sys.exit(1)
surah, ayah, score = detected
right = "" if EXPECT is None else (" correct" if surah == EXPECT else f" WRONG (expected {EXPECT})")
print(f"detected {surah}:{ayah} score={score} after {detected_at:.1f}s{right}")
sys.exit(0 if (EXPECT is None or surah == EXPECT) else 1)
