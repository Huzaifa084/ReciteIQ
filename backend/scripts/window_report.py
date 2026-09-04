"""Per-window diagnostics report for a phoneme session (P1-7 / M0-pre).

Reads the backend's structured window logs and prints one row per window plus
latency percentiles. Works for LIVE BROWSER sessions, which is the only way to
measure the recorder.ts resampler (ws_client bypasses it entirely).

Usage:
    docker logs reciteiq-backend-1 2>&1 | python -m scripts.window_report
    docker logs reciteiq-backend-1 2>&1 | python -m scripts.window_report --session <uuid>
    docker logs reciteiq-backend-1 2>&1 | python -m scripts.window_report --last
"""

import argparse
import ast
import json
import re
import sys

_WIN = re.compile(r"phoneme window (\{.*\})")
_INFO = re.compile(r"phoneme client_info (\{.*\})")


modes: dict[str, object] = {}   # session -> raw_audio flag from client_info


def parse(stream):
    """Pull window records out of the log stream (they are python-repr dicts
    embedded in a JSON log envelope)."""
    rows = []
    for line in stream:
        try:                                    # log envelope is JSON
            msg = json.loads(line).get("msg", "")
        except (json.JSONDecodeError, AttributeError):
            msg = line
        if (i := _INFO.search(msg)) is not None:
            try:
                info = ast.literal_eval(i.group(1))
                modes[info.get("session", "?")] = info.get("raw_audio")
            except (ValueError, SyntaxError):
                pass
            continue
        m = _WIN.search(msg)
        if not m:
            continue
        try:
            rows.append(ast.literal_eval(m.group(1)))
        except (ValueError, SyntaxError):
            continue
    return rows


def pct(vals, p):
    if not vals:
        return 0
    v = sorted(vals)
    return v[min(int(len(v) * p), len(v) - 1)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", help="only this session id")
    ap.add_argument("--last", action="store_true", help="only the most recent session")
    a = ap.parse_args()

    rows = parse(sys.stdin)
    if a.session:
        rows = [r for r in rows if r.get("session", "").startswith(a.session)]
    elif a.last and rows:
        rows = [r for r in rows if r.get("session") == rows[-1].get("session")]
    if not rows:
        print("no window records found")
        return

    sessions = sorted({r.get("session", "?") for r in rows})
    print(f"{len(rows)} windows across {len(sessions)} session(s)")
    for sid in sessions:
        if sid in modes:
            print(f"  {sid[:8]}  raw_audio={modes[sid]} "
                  f"({'WebRTC processing OFF' if modes[sid] else 'WebRTC processing ON'})")
    def _f(v, spec, dash="-"):
        return dash if v is None else format(v, spec)

    hdr = (f"\n{'win_s':>6} {'closed':>10} {'ms':>6} {'ids':>4} {'id/s':>5} "
           f"{'rms_dB':>7} {'peak_dB':>8} {'blank':>6} {'c_ctc':>6} "
           f"{'chain':>5} {'meanCER':>8} {'closest':>8} {'outcome':>12}  matched")
    print(hdr)
    print("-" * (len(hdr) + 12))
    for r in rows:
        print(f"{r.get('window_sec', 0):6.2f} {r.get('closed', '?'):>10} "
              f"{r.get('infer_ms', 0):6d} {r.get('n_ids', 0):4d} "
              f"{_f(r.get('ids_per_sec'), '5.2f'):>5} "
              f"{_f(r.get('rms_dbfs'), '7.1f'):>7} "
              f"{_f(r.get('peak_dbfs'), '8.1f'):>8} "
              f"{_f(r.get('blank_frac'), '6.3f'):>6} "
              f"{_f(r.get('c_ctc'), '6.3f'):>6} "
              f"{r.get('chain_len', 0):5d} "
              f"{_f(r.get('chain_mean_cer'), '8.3f'):>8} "
              f"{r.get('closest_cer', float('nan')):8.3f} "
              f"{r.get('outcome', '?'):>12}  {r.get('matched_ayahs', [])}")

    ms = [r["infer_ms"] for r in rows if "infer_ms" in r]
    secs = [r["window_sec"] for r in rows if "window_sec" in r]
    print(f"\ninfer_ms   p50={pct(ms, .5)} p95={pct(ms, .95)} max={max(ms) if ms else 0}")
    print(f"window_sec p50={pct(secs, .5):.2f} total_audio={sum(secs):.1f}s")

    outcomes: dict[str, int] = {}
    for r in rows:
        outcomes[r.get("outcome", "?")] = outcomes.get(r.get("outcome", "?"), 0) + 1
    print(f"outcomes   {outcomes}")

    matched = sorted({n for r in rows for n in r.get("matched_ayahs", [])})
    nomatch = outcomes.get("no_match", 0)
    print(f"ayahs credited: {matched}")
    if nomatch:
        print(f"** {nomatch} window(s) matched NOTHING — closest CERs: "
              f"{[r.get('closest_cer') for r in rows if r.get('outcome') == 'no_match']}")

    # Token starvation is the signature of an input problem rather than a
    # matching problem: qari audio yields ~4.5 IDs/sec, so anything far below
    # that means the model saw little it could label.
    rates = [r["ids_per_sec"] for r in rows if r.get("ids_per_sec") is not None]
    levels = [r["rms_dbfs"] for r in rows if r.get("rms_dbfs") is not None]
    if rates:
        starved = [r for r in rates if r < 2.0]
        print(f"ids_per_sec p50={pct(rates, .5):.2f} (qari reference ~4.5); "
              f"{len(starved)}/{len(rates)} window(s) below 2.0/s")
    if levels:
        print(f"rms_dbfs   p50={pct(levels, .5):.1f} min={min(levels):.1f} "
              f"max={max(levels):.1f}  (-30 to -18 dBFS is a healthy mic level)")


if __name__ == "__main__":
    main()
