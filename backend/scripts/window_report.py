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


def parse(stream):
    """Pull window records out of the log stream (they are python-repr dicts
    embedded in a JSON log envelope)."""
    rows = []
    for line in stream:
        try:                                    # log envelope is JSON
            msg = json.loads(line).get("msg", "")
        except (json.JSONDecodeError, AttributeError):
            msg = line
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
    hdr = (f"\n{'win_s':>6} {'closed':>10} {'ms':>6} {'ids':>4} {'c_ctc':>6} "
           f"{'chain':>5} {'meanCER':>8} {'closest':>8} {'outcome':>12}  matched")
    print(hdr)
    print("-" * (len(hdr) + 12))
    for r in rows:
        cc = r.get("c_ctc")
        mc = r.get("chain_mean_cer")
        print(f"{r.get('window_sec', 0):6.2f} {r.get('closed', '?'):>10} "
              f"{r.get('infer_ms', 0):6d} {r.get('n_ids', 0):4d} "
              f"{('-' if cc is None else f'{cc:.3f}'):>6} "
              f"{r.get('chain_len', 0):5d} "
              f"{('-' if mc is None else f'{mc:.3f}'):>8} "
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


if __name__ == "__main__":
    main()
