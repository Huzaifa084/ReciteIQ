"""Concurrency and failure-recovery check against a running backend.

Covers what unit tests cannot: real sessions competing for one serialised model
inside the container's memory limit, and what happens at the admission cap.

usage: staging_concurrency.py <base_url> <wav> <surah_id> <n_sessions>
"""
import json
import subprocess
import sys
import threading
import time
import wave

import requests
from websockets.sync.client import connect

base, wav_path, surah, n = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
with wave.open(wav_path) as w:
    pcm = w.readframes(w.getnframes())
dur = len(pcm) / 2 / 16000

results: list[dict] = []
lock = threading.Lock()


def run_one(tag: str):
    out = {"tag": tag, "events": 0, "ayahs": set(), "rejected": None, "error": None}
    try:
        sid = requests.post(f"{base}/api/sessions",
                            json={"surah_id": surah, "start_ayah": 1},
                            timeout=15).json()["session_id"]
        ws_url = base.replace("http://", "ws://") + f"/ws/session/{sid}"
        t0 = time.perf_counter()
        with connect(ws_url, open_timeout=30, max_size=None) as ws:
            for i in range(0, len(pcm), 3200):
                ws.send(pcm[i:i + 3200])
                target = t0 + (i + 3200) / 2 / 16000 / 1.05
                while (slack := target - time.perf_counter()) > 0:
                    try:
                        m = json.loads(ws.recv(timeout=slack))
                    except TimeoutError:
                        break
                    if m.get("type") == "events":
                        out["events"] += len(m["events"])
                        out["ayahs"] |= {e["payload"]["ayah"] for e in m["events"]
                                         if e["type"] == "WORD_OK"}
                    elif m.get("type") == "rejected":
                        out["rejected"] = m.get("reason")
                        return
            ws.send(json.dumps({"type": "end"}))
        requests.post(f"{base}/api/sessions/{sid}/end", timeout=30)
    except Exception as e:                     # noqa: BLE001 - reported, not swallowed
        out["error"] = f"{type(e).__name__}: {e}"
    finally:
        out["ayahs"] = len(out["ayahs"])
        with lock:
            results.append(out)


def mem():
    o = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}",
                        "reciteiq-staging-backend-staging-1"],
                       capture_output=True, text=True).stdout.strip()
    return o or "?"


peak = []
stop = threading.Event()


def sample():
    while not stop.is_set():
        peak.append(mem())
        time.sleep(3)


threads = [threading.Thread(target=run_one, args=(f"s{i}",)) for i in range(n)]
mon = threading.Thread(target=sample)
mon.start()
t0 = time.perf_counter()
for t in threads:
    t.start()
for t in threads:
    t.join()
stop.set(); mon.join()
wall = time.perf_counter() - t0

print(f"\n{n} concurrent sessions, {dur:.0f}s clip each, wall {wall:.0f}s")
for r in sorted(results, key=lambda x: x["tag"]):
    print(f"  {r['tag']}: events={r['events']} ayahs={r['ayahs']} "
          f"rejected={r['rejected']} error={r['error']}")
print(f"memory samples: {len(peak)}  peak={max(peak, default='?')}")

ok = [r for r in results if r["error"] is None and r["rejected"] is None]
rej = [r for r in results if r["rejected"]]
print(f"\nadmitted {len(ok)}  rejected {len(rej)}  errored "
      f"{len([r for r in results if r['error']])}")
# Every admitted session must have made real progress; a shed session must say so
# cleanly rather than erroring.
bad = [r for r in ok if r["ayahs"] == 0] + [r for r in results if r["error"]]
print("CONCURRENCY " + ("FAIL: " + json.dumps(bad) if bad else "PASS"))
sys.exit(1 if bad else 0)
