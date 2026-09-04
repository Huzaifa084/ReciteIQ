"""End-to-end smoke test against a running backend: real audio over the real
WebSocket, then the real summary endpoint.

The release gate replays cached transcripts through the detector, which is the
right way to iterate on detector logic but proves nothing about the server: the
engine flag, the segmentation the engine picks, the lock, the event stream, the
finaliser and the schema are all untested by it. This drives the whole path.

usage: staging_smoke.py <base_url> <wav> <surah_id> [expected_ayahs]
       staging_smoke.py http://127.0.0.1:19844 clip.wav 84 25
"""
import json
import sys
import time
import wave

import requests
from websockets.sync.client import connect

base, wav_path, surah = sys.argv[1], sys.argv[2], int(sys.argv[3])
expect = int(sys.argv[4]) if len(sys.argv) > 4 else None

with wave.open(wav_path) as w:
    assert w.getframerate() == 16000 and w.getnchannels() == 1, "need 16k mono"
    pcm = w.readframes(w.getnframes())
dur = len(pcm) / 2 / 16000
print(f"clip {wav_path}  {dur:.1f}s  surah {surah}")

r = requests.post(f"{base}/api/sessions", json={"surah_id": surah, "start_ayah": 1}, timeout=10)
r.raise_for_status()
sid = r.json()["session_id"]
print(f"session {sid}")

ws_url = base.replace("http://", "ws://").replace("https://", "wss://") + f"/ws/session/{sid}"
events, frames = [], 0
CHUNK = 3200          # 0.1s of 16k mono s16le
t0 = time.perf_counter()
with connect(ws_url, open_timeout=30, max_size=None) as ws:
    for i in range(0, len(pcm), CHUNK):
        ws.send(pcm[i:i + CHUNK])
        frames += 1
        # The server rejects ingest faster than 1.1x real time (D3), so pace it.
        target = t0 + (i + CHUNK) / 2 / 16000 / 1.05
        while (slack := target - time.perf_counter()) > 0:
            try:
                msg = ws.recv(timeout=slack)
            except TimeoutError:
                break
            m = json.loads(msg)
            if m.get("type") == "events":
                events += m["events"]
                print(f"  +{time.perf_counter()-t0:6.1f}s asr_ms={m.get('asr_ms')} "
                      f"seg={m.get('segment_s')}s types="
                      f"{sorted({e['type'] for e in m['events']})}")
            elif m.get("type") in ("rejected", "ended"):
                print(f"  server said: {m}")
    ws.send(json.dumps({"type": "end"}))
    deadline = time.perf_counter() + 60
    while time.perf_counter() < deadline:
        try:
            m = json.loads(ws.recv(timeout=deadline - time.perf_counter()))
        except (TimeoutError, Exception):
            break
        if m.get("type") == "events":
            events += m["events"]
        elif m.get("type") == "ended":
            break

wall = time.perf_counter() - t0
requests.post(f"{base}/api/sessions/{sid}/end", timeout=30)
s = requests.get(f"{base}/api/sessions/{sid}/summary", timeout=10).json()["summary"]

ok_ayahs = {e["payload"]["ayah"] for e in events
            if e["type"] == "WORD_OK" and e["state"] == "confirmed"}
print(f"\nwall {wall:.1f}s for {dur:.1f}s audio ({wall/dur:.2f}x)  frames={frames}")
print(f"events {len(events)}  ayahs touched {len(ok_ayahs)}")
print("summary:", json.dumps(s, ensure_ascii=False))

fail = []
if s is None:
    fail.append("no summary row written")
else:
    if s["words_ok"] == 0:
        fail.append("summary credits zero words")
    for k in ("repeats", "uncertain"):
        if k not in s:
            fail.append(f"summary missing {k}")
if expect and len(ok_ayahs) < expect:
    fail.append(f"only {len(ok_ayahs)}/{expect} ayahs reached")

print("\nSMOKE " + ("FAIL: " + "; ".join(fail) if fail else "PASS"))
sys.exit(1 if fail else 0)
