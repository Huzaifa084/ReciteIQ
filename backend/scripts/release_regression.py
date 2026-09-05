"""Post-flip regression: the six named cases, end to end against a live server.

Real audio over the real WebSocket, real summary endpoint. This is the suite to
re-run after any deploy that touches the ASR path or the tracker.

usage: release_regression.py <base_url>
"""
import json
import subprocess
import sys
import time
import wave
from pathlib import Path

import requests
from websockets.sync.client import connect

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:19843"
CLIPS = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(
    "/tmp/claude-0/-root/2257e947-aa0a-4678-81b2-5bb386c8707f/scratchpad")

# (name, wav, surah, expectation)
CASES = [
    ("Al-Fatihah clean",        "eval16k/fatiha.wav",             1,   "clean"),
    ("Al-Fatihah skipped word", "err16k/fatiha__skip_word.wav",    1,   "missed_word"),
    ("Al-Fatihah skipped ayah", "err16k/fatiha__skip_ayah3.wav",   1,   ("missed_ayah", 3)),
    ("Al-Kafirun 3->5",         "err16k/kaferoon__skip_ayah4.wav", 109, ("missed_ayah", 4)),
    ("Al-Kafirun repeat",       "err16k/kaferoon__repeat_ayah2.wav", 109, "repeat_or_clean"),
    ("Az-Zalzalah substitution","eval16k/zilzal_err.wav",          99,  "missed_word"),
    ("Al-Inshiqaq long clean",  "eval16k/inshiqaq.wav",            84,  "clean"),
]


def run(wav: Path, surah: int):
    with wave.open(str(wav)) as w:
        pcm = w.readframes(w.getnframes())
    ayahs = requests.get(f"{BASE}/api/surahs/{surah}/text", timeout=15).json()
    n_words = sum(len(a["words"]) for a in ayahs)
    sid = requests.post(f"{BASE}/api/sessions",
                        json={"surah_id": surah, "start_ayah": 1},
                        timeout=15).json()["session_id"]
    ws_url = BASE.replace("https://", "wss://").replace("http://", "ws://")
    events, t0 = [], time.perf_counter()
    with connect(f"{ws_url}/ws/session/{sid}", open_timeout=30, max_size=None) as ws:
        for i in range(0, len(pcm), 3200):
            ws.send(pcm[i:i + 3200])
            target = t0 + (i + 3200) / 2 / 16000 / 1.05
            while (slack := target - time.perf_counter()) > 0:
                try:
                    m = json.loads(ws.recv(timeout=slack))
                except TimeoutError:
                    break
                if m.get("type") == "events":
                    events += m["events"]
        ws.send(json.dumps({"type": "end"}))
        deadline = time.perf_counter() + 90
        while time.perf_counter() < deadline:
            try:
                m = json.loads(ws.recv(timeout=deadline - time.perf_counter()))
            except Exception:
                break
            if m.get("type") == "events":
                events += m["events"]
            elif m.get("type") == "ended":
                break
    requests.post(f"{BASE}/api/sessions/{sid}/end", timeout=60)
    s = requests.get(f"{BASE}/api/sessions/{sid}/summary", timeout=15).json()["summary"]
    return s, events, n_words, len(ayahs), round(time.perf_counter() - t0, 1)


def confirmed(events, t):
    return [e for e in events if e["type"] == t and e["state"] == "confirmed"]


rows, failed = [], 0
for name, rel, surah, expect in CASES:
    s, ev, n_words, n_ayahs, wall = run(CLIPS / rel, surah)
    ok_ayahs = len({e["payload"]["ayah"] for e in confirmed(ev, "WORD_OK")})
    why = []
    if s is None:
        why.append("no summary")
    else:
        if s["words_ok"] > n_words:
            why.append(f"words_ok {s['words_ok']} > {n_words} reference words")
        if expect == "clean":
            if s["words_missed"] or s["ayahs_missed"] or s["jumps"]:
                why.append(f"false errors on a clean recitation: {s}")
            if ok_ayahs < n_ayahs:
                why.append(f"only reached {ok_ayahs}/{n_ayahs} ayahs")
        elif expect == "missed_word":
            if not s["words_missed"]:
                why.append("no MISSED_WORD raised")
        elif isinstance(expect, tuple) and expect[0] == "missed_ayah":
            named = any(e["payload"].get("ayah") == expect[1]
                        for e in confirmed(ev, "MISSED_AYAH"))
            if not (named or s["jumps"]):
                why.append(f"ayah {expect[1]} skip not reported")
        elif expect == "repeat_or_clean":
            # The RNN-T collapses an ayah repeated inside one window, so the
            # REPEAT may not reach the detector at all. What must NOT happen is
            # a false error (gate-release.md R4).
            if s["words_missed"] or s["ayahs_missed"] or s["jumps"]:
                why.append(f"repeat produced a false error: {s}")
    verdict = "PASS" if not why else "FAIL"
    failed += verdict == "FAIL"
    rows.append((verdict, name, ok_ayahs, n_ayahs, s, wall, why))
    print(f"{verdict}  {name:26s} ayahs={ok_ayahs}/{n_ayahs} {wall:5.1f}s  "
          f"{json.dumps(s, ensure_ascii=False) if s else 'None'}")
    for w in why:
        print(f"       ! {w}")

print(f"\nREGRESSION {len(rows)-failed}/{len(rows)} pass")
sys.exit(1 if failed else 0)
