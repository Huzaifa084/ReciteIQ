"""Run concurrency test (1, 2, 3 sessions) against the live running container.
"""
import asyncio
import json
import subprocess
import time
import wave
from pathlib import Path
import httpx
import websockets

AUDIO_PATH = Path("/tmp/claude-0/-root/2257e947-aa0a-4678-81b2-5bb386c8707f/scratchpad/eval16k/fatiha.wav")
BASE_URL = "http://127.0.0.1:18000"
WS_URL = "ws://127.0.0.1:18000"
CONTAINER_NAME = "reciteiq-fc-memtest"

def run_cmd(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)

def get_container_mem_mb():
    res = run_cmd(f"docker stats --no-stream --format '{{{{.MemUsage}}}}' {CONTAINER_NAME}")
    if res.returncode != 0 or not res.stdout.strip():
        return None
    raw = res.stdout.strip().split("/")[0].strip()
    if "GiB" in raw:
        return float(raw.replace("GiB", "").strip()) * 1024.0
    elif "MiB" in raw:
        return float(raw.replace("MiB", "").strip())
    elif "MB" in raw:
        return float(raw.replace("MB", "").strip())
    return None

async def run_single_session(client, pcm_chunks, session_idx):
    # 1. Create session
    r = await client.post(f"{BASE_URL}/api/sessions", json={"surah_id": 1, "start_ayah": 1})
    if r.status_code != 200:
        raise RuntimeError(f"Session {session_idx} create failed: {r.status_code} {r.text}")
    sess_id = r.json()["session_id"]

    events = []
    t_start = time.perf_counter()
    first_ok_time = None
    ws_uri = f"{WS_URL}/ws/session/{sess_id}"
    async with websockets.connect(ws_uri) as ws:
        async def receiver():
            nonlocal first_ok_time
            try:
                async for msg in ws:
                    try:
                        data = json.loads(msg)
                        events.append(data)
                        if first_ok_time is None and data.get("type") == "word_ok":
                            first_ok_time = time.perf_counter() - t_start
                    except Exception:
                        pass
            except websockets.exceptions.ConnectionClosed:
                pass

        recv_task = asyncio.create_task(receiver())

        # Stream audio chunks at near real-time (0.5s chunks sent every ~0.35s)
        for chunk in pcm_chunks:
            await ws.send(chunk)
            await asyncio.sleep(0.35)

        # Allow extra time for final VAD flush / inference
        await asyncio.sleep(3.0)
        await ws.close()
        recv_task.cancel()
        try:
            await recv_task
        except asyncio.CancelledError:
            pass

    duration = time.perf_counter() - t_start
    confirmed_words = sum(1 for e in events if e.get("type") in ("WORD_OK", "word_ok") and e.get("state") in ("confirmed", "CONFIRMED"))
    return {
        "session_idx": session_idx,
        "session_id": sess_id,
        "duration": duration,
        "first_ok_time": first_ok_time,
        "events_count": len(events),
        "confirmed_words": confirmed_words,
    }

async def run_concurrency(n, pcm_chunks):
    t0 = time.perf_counter()
    async with httpx.AsyncClient() as client:
        tasks = [asyncio.create_task(run_single_session(client, pcm_chunks, i)) for i in range(n)]
        mem_samples = []
        async def sampler():
            while not all(t.done() for t in tasks):
                m = get_container_mem_mb()
                if m is not None:
                    mem_samples.append(m)
                await asyncio.sleep(0.4)

        sample_task = asyncio.create_task(sampler())
        results = await asyncio.gather(*tasks)
        await sample_task

    wall_time = time.perf_counter() - t0
    peak_mem = max(mem_samples) if mem_samples else get_container_mem_mb()
    return {
        "concurrency": n,
        "wall_time": wall_time,
        "peak_mem_mb": peak_mem,
        "results": results,
    }

async def main():
    with wave.open(str(AUDIO_PATH)) as w:
        audio_bytes = w.readframes(w.getnframes())
    chunk_size = 16000
    pcm_chunks = [audio_bytes[i:i+chunk_size] for i in range(0, len(audio_bytes), chunk_size)]
    print(f"Loaded audio: {len(audio_bytes)} bytes ({len(pcm_chunks)} chunks of 0.5s, total ~31s audio)")

    steady_rss = get_container_mem_mb()
    print(f"Steady-state RSS before load: {steady_rss:.1f} MB (Headroom: {2560.0 - steady_rss:.1f} MB)")

    all_cr = []
    for n in (1, 2, 3):
        print(f"\n==========================================")
        print(f"=== Testing {n} Concurrent Session(s) ===")
        print(f"==========================================")
        cr = await run_concurrency(n, pcm_chunks)
        all_cr.append(cr)
        print(f"Wall time:       {cr['wall_time']:.2f}s")
        print(f"Peak RSS:        {cr['peak_mem_mb']:.1f} MB")
        print(f"Headroom:        {2560.0 - cr['peak_mem_mb']:.1f} MB")
        for res_i in cr["results"]:
            ttf_str = f"{res_i['first_ok_time']:.2f}s" if res_i['first_ok_time'] is not None else "N/A"
            print(f"  Session {res_i['session_idx']}: {res_i['confirmed_words']} confirmed words, TTF={ttf_str}, dur={res_i['duration']:.2f}s")
        await asyncio.sleep(2.0)

    print("\n================ SUMMARY ================")
    print(f"Steady RSS: {steady_rss:.1f} MB")
    for cr in all_cr:
        print(f"{cr['concurrency']} session(s): Peak RSS = {cr['peak_mem_mb']:.1f} MB (Headroom: {2560.0 - cr['peak_mem_mb']:.1f} MB), Wall: {cr['wall_time']:.2f}s")

    with open("/tmp/live_concurrency_report.json", "w") as f:
        json.dump({"steady_rss_mb": steady_rss, "concurrency": all_cr}, f, indent=2)
    print("Report saved to /tmp/live_concurrency_report.json")

if __name__ == "__main__":
    asyncio.run(main())
