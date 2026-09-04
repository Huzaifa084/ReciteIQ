"""Gate 1: Real container-level memory & concurrency test for FastConformer.

Runs a real Docker container constrained to 2560 MB with:
- FastConformer ASR loaded
- FastAPI loaded
- PostgreSQL connection pool loaded
- Silero VAD loaded
Measures:
- Cold startup time
- Steady-state container RSS
- Peak RSS and latency under 1, 2, and 3 concurrent sessions
"""
import asyncio
import json
import subprocess
import sys
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

async def wait_healthy(timeout=120.0):
    t0 = time.perf_counter()
    async with httpx.AsyncClient() as client:
        while time.perf_counter() - t0 < timeout:
            try:
                r = await client.get(f"{BASE_URL}/healthz", timeout=1.0)
                if r.status_code == 200:
                    return time.perf_counter() - t0
            except Exception:
                pass
            await asyncio.sleep(0.3)
    raise TimeoutError(f"Container failed to become healthy within {timeout}s")

async def run_single_session(client, pcm_chunks, session_idx):
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
                        if data.get("type") == "events":
                            for ev in data.get("events", []):
                                events.append(ev)
                                if first_ok_time is None and ev.get("type") == "WORD_OK":
                                    first_ok_time = time.perf_counter() - t_start
                        else:
                            events.append(data)
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
    confirmed_words = sum(1 for e in events if e.get("type") == "WORD_OK" and e.get("state") == "confirmed")
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
    print("=== Starting Gate 1: Container-Level Memory Test ===")
    run_cmd(f"docker rm -f {CONTAINER_NAME} 2>/dev/null")

    with wave.open(str(AUDIO_PATH)) as w:
        audio_bytes = w.readframes(w.getnframes())
    chunk_size = 16000
    pcm_chunks = [audio_bytes[i:i+chunk_size] for i in range(0, len(audio_bytes), chunk_size)]
    print(f"Loaded {len(audio_bytes)} bytes audio ({len(pcm_chunks)} chunks of 0.5s, total ~31s audio)")

    cmd = (
        f"docker run -d "
        f"--name {CONTAINER_NAME} "
        f"--network reciteiq_default "
        f"-p 127.0.0.1:18000:8000 "
        f"--memory=2560m "
        f"--cpus=2.0 "
        f"-v /opt/apps/ReciteIQ/backend/app:/app/app:ro "
        f"-v /opt/apps/ReciteIQ/backend/models:/app/models:ro "
        f"-v /root/.cache/huggingface:/root/.cache/huggingface:ro "
        f"-e HF_HOME=/root/.cache/huggingface "
        f"-e HF_HUB_OFFLINE=1 "
        f"-e RECITEIQ_DATABASE_URL=postgresql+psycopg://reciteiq:reciteiq@db:5432/reciteiq "
        f"-e RECITEIQ_ASR_ENGINE=fastconformer "
        f"-e RECITEIQ_TRACKER_MODE=whisper "
        f"-e RECITEIQ_MAX_SESSIONS_PER_IP=5 "
        f"-e OMP_NUM_THREADS=2 "
        f"reciteiq-backend:fastconformer"
    )
    t_start = time.perf_counter()
    print("Launching container...")
    res = run_cmd(cmd)
    if res.returncode != 0:
        print(f"Failed to run container: {res.stderr}")
        return 1

    print("Waiting for cold startup and warmup...")
    cold_startup_s = await wait_healthy(timeout=120.0)
    print(f"Cold startup time: {cold_startup_s:.2f} seconds")

    await asyncio.sleep(2.0)
    steady_rss = get_container_mem_mb()
    print(f"Steady-state RSS (FastConformer + FastAPI + DB + VAD loaded): {steady_rss:.1f} MB")
    print(f"Headroom against 2560 MB limit: {2560.0 - steady_rss:.1f} MB")

    concurrency_results = []
    for n in (1, 2, 3):
        print(f"\n--- Testing {n} concurrent session(s) ---")
        cr = await run_concurrency(n, pcm_chunks)
        concurrency_results.append(cr)
        print(f"  Sessions: {n}")
        print(f"  Wall time: {cr['wall_time']:.2f}s")
        print(f"  Peak RSS:  {cr['peak_mem_mb']:.1f} MB")
        print(f"  Headroom:  {2560.0 - cr['peak_mem_mb']:.1f} MB")
        for res_i in cr["results"]:
            ttf_str = f"{res_i['first_ok_time']:.2f}s" if res_i['first_ok_time'] is not None else "N/A"
            print(f"    Session {res_i['session_idx']}: {res_i['confirmed_words']} words confirmed, TTF={ttf_str}, duration={res_i['duration']:.2f}s")
        await asyncio.sleep(2.0)

    dmesg_check = run_cmd("dmesg -T | grep -i oom | tail -n 5").stdout.strip()
    container_inspect = run_cmd(f"docker inspect {CONTAINER_NAME} --format '{{{{.State.OOMKilled}}}}'").stdout.strip()

    final_report = {
        "cold_startup_s": cold_startup_s,
        "steady_rss_mb": steady_rss,
        "concurrency": concurrency_results,
        "oom_killed": container_inspect == "true",
        "dmesg_oom": dmesg_check,
    }
    with open("/tmp/container_gate_report.json", "w") as f:
        json.dump(final_report, f, indent=2)

    print("\n=== Gate 1 Summary ===")
    print(f"Cold startup: {cold_startup_s:.2f}s")
    print(f"Steady RSS:   {steady_rss:.1f} MB")
    for cr in concurrency_results:
        print(f"{cr['concurrency']} session(s): Peak RSS = {cr['peak_mem_mb']:.1f} MB (Headroom: {2560.0 - cr['peak_mem_mb']:.1f} MB), Wall: {cr['wall_time']:.2f}s")
    print(f"OOM Killed:   {container_inspect}")
    print("Report saved to /tmp/container_gate_report.json")

    run_cmd(f"docker rm -f {CONTAINER_NAME} 2>/dev/null")
    print("Container cleaned up.")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
