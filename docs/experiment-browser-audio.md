# Browser audio processing A/B (2026-09-04)

Three live browser takes of Al-Fatihah by the same reciter, captured with the
P0-3/P1-7 diagnostics. `?rawaudio=1` disables `echoCancellation`,
`noiseSuppression` and `autoGainControl` in `getUserMedia`.

| session | mode | device | credited | matched-window CER | no_match | rms dBFS |
|---|---|---|---|---|---|---|
| `9f834776` | processing **ON** | laptop | **1/7** | mean 0.210 (0.148–0.259) | 7/10 | −38.6 … −20.9 |
| `a765b6a2` | processing **OFF** | laptop | **5/7** | mean 0.330 (0.188–0.375) | 3/8 | −19.6 … −17.2 |
| `d370ad27` | processing **OFF** | mobile | **6/7** | mean 0.080 (**0.000–0.250**) | 3/8 | −41.8 … −32.2 |

## Result: WebRTC voice processing was the primary cause

Turning it off took credited ayahs from **1 → 5** on the same laptop, and **1 → 6**
on mobile. The mobile take produced per-ayah CERs of **0.037, 0.000, 0.000, 0.113,
0.250** — better than the professional eval clip scores against its own reference.

`recorder.ts` had requested `echoCancellation: true, noiseSuppression: true`, and
Chrome defaults `autoGainControl` on. All three are tuned for telephony
intelligibility, not phoneme recognition: spectral gating removes content, AEC
applies nonlinear processing, and AGC pumps the level — all of which smear the
sustained *madd* vowels recitation is full of.

**This is why the earlier resampler A/B found nothing.** WebRTC processing happens
inside the browser *before* audio reaches the AudioWorklet, so feeding files
through a simulated resampler bypassed it entirely. The conclusion that "the
capture path is harmless" was drawn from the wrong half of the capture path.

## Level is definitively NOT the driver

The **quietest** session by a wide margin (mobile, −41.8 … −32.2 dBFS) has the
**best** CERs (mean 0.080), while the loudest (laptop, processing off, −19.6 …
−17.2) sits at 0.330. The earlier "too quiet" hypothesis is dead: what matters is
whether the audio was processed, not how loud it is.

## A second, separate bug this exposed

The processing-off laptop take turned **ayahs 1 and 2 red**. Cause, verified:

```
1:1 = بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ   (27 ids)
1:3 =            الرَّحْمَٰنِ الرَّحِيمِ   (16 ids)

ayah 3's reference inside ayah 1's reference: CER 0.125  (MATCH_CER_MAX = 0.45)
```

**Al-Fatihah 1:3 is literally the last two words of 1:1**, so its reference sits
inside ayah 1's at CER 0.125 — far under the gate. A window holding only the
basmalah therefore chains to **ayah 3**, which advances the pointer past ayahs 1–2
and reports them missed. The session log confirms the order: the first window
chained `[3]`, then `[2]`, `[4]`, `[5]`, `[6]`.

This is the same class of failure as Al-Kafirun 3/5 — a within-surah substring
ambiguity that a single pointer cannot resolve — and it is a second concrete
motivating case for the beam tracker (**P1-5**). Note also that
`phoneme_revoke_late_miss` would have healed half of it: ayah 2 *was* credited by
a later window, so its red would have been withdrawn.

## Recommended changes

1. **Make raw audio the default** — disable `echoCancellation`, `noiseSuppression`
   and `autoGainControl`, keeping `?rawaudio=0` as an escape hatch. This is the
   single largest measured improvement in the project so far (1 → 5/6 ayahs).
2. **Enable `phoneme_revoke_late_miss`** — it withdraws exactly the kind of false
   red seen here once a later window proves the ayah was recited.
3. **Carry-forward stays off for now.** These takes are not fragmented (window p50
   3.5–4.0s, ayah-sized), so it would not have helped; keep it for genuinely
   fragmented takes.
4. **P1-5 (beam) now has two motivating cases**, not one: Al-Kafirun 3/5 and
   Al-Fatihah 1:3 ⊂ 1:1.

## Caveats

- One reciter, one surah, one take per configuration. The effect size (1 → 5/6) is
  far larger than run-to-run noise seen elsewhere, but this is not a corpus.
- Laptop and mobile differ in mic and room as well as configuration, so the
  device comparison is confounded; the *within-laptop* ON→OFF comparison
  (1 → 5) is the clean one.
- Ayah 7 remains unmatched in all three takes (closest CER 0.645–0.774). It is the
  longest ayah and needs its own look.
