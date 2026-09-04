"""Ayah 7: is the failure CTC decoding, reference mismatch, length, or segmentation?

Test the length hypothesis directly: feed the model the WHOLE recitation as one
long stream (no windowing) and see whether ayah 7 then matches.
"""
import wave
import numpy as np
from sqlalchemy import select
from app.asr.phoneme_ctc import get_phoneme_ctc
from app.db.models import Ayah
from app.db.session import SessionLocal
from app.engine.phoneme_tracker import PhonemeTracker

with wave.open("/tmp/claude-0/-root/2257e947-aa0a-4678-81b2-5bb386c8707f/scratchpad/user_fatiha.wav") as w:
    pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16)
audio = pcm.astype(np.float32) / 32768.0

m = get_phoneme_ctc()
CHUNK = 25 * 16000
ids = []
for i in range(0, len(audio), CHUNK):
    ids += m.recognize(audio[i:i + CHUNK]).ids

db = SessionLocal()
rows = db.execute(select(Ayah).where(Ayah.surah_id == 1).order_by(Ayah.number)).scalars().all()
ref = {a.number: list(a.phoneme_ids) for a in rows}
db.close()
tr = PhonemeTracker(ref=[])

print(f"whole-take stream: {len(ids)} ids from {len(audio)/16000:.1f}s\n")
print(f"{'ayah':>4} {'ref_len':>8} {'CER(full stream)':>17} {'<=0.45':>7}")
for n in sorted(ref):
    cer, s, e = tr._best_span(ids, ref[n])
    print(f"{n:>4} {len(ref[n]):>8} {cer:>17.3f} {'YES' if cer <= 0.45 else 'no':>7}")

# now the same ayah 7 reference against progressively larger prefixes of a window
print("\nayah 7 (63 ids) scored against windows of increasing length:")
cer7, s7, e7 = tr._best_span(ids, ref[7])
print(f"  best span in the full stream: CER {cer7:.3f} at [{s7}:{e7}] (len {e7-s7})")
for w in (20, 26, 32, 40, 47, 55, 63, 70):
    seg = ids[max(0, s7): max(0, s7) + w]
    c, _a, _b = tr._best_span(seg, ref[7])
    print(f"  window of {w:>3} ids -> CER {c:.3f}"
          + ("   (below 0.75*63=47: no candidate span exists)" if w < 47 else ""))
