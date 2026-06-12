"""CLI WS test client: create a session, stream a WAV at ~real-time, print events.

Usage: python -m scripts.ws_client <wav> <surah_id> [start_ayah] [--fast]
       --fast streams at 4x real-time for load tests (bypasses politeness,
       the server's rate cap will then kick in — useful to test it).
"""

import asyncio
import json
import sys
import wave

import httpx
import websockets

API = "http://127.0.0.1:8000"
WS = "ws://127.0.0.1:8000"
CHUNK_MS = 250


async def run(wav_path: str, surah_id: int, start_ayah: int, fast: bool, auto: bool = False) -> dict:
    body = {"auto": True} if auto else {"surah_id": surah_id, "start_ayah": start_ayah}
    r = httpx.post(f"{API}/api/sessions", json=body)
    r.raise_for_status()
    sid = r.json()["session_id"]
    print(f"session {sid}{' (auto-detect)' if auto else ''}")

    with wave.open(wav_path, "rb") as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1 and w.getsampwidth() == 2
        pcm = w.readframes(w.getnframes())

    chunk_bytes = int(16000 * 2 * CHUNK_MS / 1000)
    counts: dict[str, int] = {}
    asr_ms: list[int] = []
    done = asyncio.Event()

    async with websockets.connect(f"{WS}/ws/session/{sid}", max_size=None) as ws:

        async def reader():
            async for raw in ws:
                msg = json.loads(raw)
                if msg["type"] == "events":
                    if "asr_ms" in msg:
                        asr_ms.append(msg["asr_ms"])
                    for e in msg["events"]:
                        key = f"{e['type']}/{e['state']}"
                        counts[key] = counts.get(key, 0) + 1
                        if e["type"] != "WORD_OK" and e["type"] != "POSITION":
                            print(f"  {key}: {e['payload']}")
                elif msg["type"] == "detected":
                    print(f"  << DETECTED: surah {msg['surah']} ayah {msg['ayah']} (score {msg['score']})")
                elif msg["type"] in ("ended", "rejected"):
                    print(f"  << {msg}")
                    done.set()
                    return

        rt = asyncio.create_task(reader())
        for i in range(0, len(pcm), chunk_bytes):
            ws_open = not done.is_set()
            if not ws_open:
                break
            await ws.send(pcm[i : i + chunk_bytes])
            await asyncio.sleep((CHUNK_MS / 1000) / (4 if fast else 1))
        if not done.is_set():
            await ws.send(json.dumps({"type": "end"}))
            await asyncio.wait_for(done.wait(), timeout=30)
        rt.cancel()

    s = httpx.get(f"{API}/api/sessions/{sid}/summary").json()
    print("\nevent counts:", json.dumps(counts, indent=2))
    if asr_ms:
        asr_sorted = sorted(asr_ms)
        print(f"asr latency ms: median={asr_sorted[len(asr_sorted)//2]} p95={asr_sorted[int(len(asr_sorted)*0.95)]}")
    print("summary:", json.dumps(s["summary"], ensure_ascii=False))
    return counts


if __name__ == "__main__":
    wav, surah = sys.argv[1], int(sys.argv[2])
    start = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].isdigit() else 1
    asyncio.run(run(wav, surah, start, "--fast" in sys.argv, "--auto" in sys.argv))
