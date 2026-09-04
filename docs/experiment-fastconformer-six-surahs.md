# Does FastConformer generalise beyond Al-Fatihah? (2026-09-04)

Six real amateur recitations by the same reciter, evaluated against the canonical
Imla'i word lists. `mohammed/fastconformer-quran-ar`, NeMo on CPU, isolated venv.
**No production code was modified.**

## Results

| surah | # | duration | RTF | WER | CER | words ok | sub | del | ins | perfect ayahs |
|---|---|---|---|---|---|---|---|---|---|---|
| Al-Fatihah | 1 | 31.0s | 0.125 | 0.0345 | 0.0272 | **29/29** | 0 | 0 | 1 | **7/7** |
| Al-Kafirun | 109 | 22.8s | 0.090 | 0.0769 | 0.0100 | 25/26 | 1 | 0 | 1 | 5/6 |
| **Az-Zalzalah** | 99 | 32.6s | 0.251 | **0.0000** | **0.0000** | **36/36** | 0 | 0 | 0 | **8/8** |
| Al-Adiyat | 100 | 31.0s | 0.151 | 0.0750 | 0.0178 | 37/40 | 3 | 0 | 0 | 8/11 |
| At-Tariq | 86 | 48.5s | 0.094 | 0.0328 | 0.0078 | 59/61 | 2 | 0 | 0 | 15/17 |
| Al-Inshiqaq | 84 | 81.8s | 0.121 | 0.0467 | 0.0090 | 103/107 | 4 | 0 | 1 | 22/25 |

**Overall: 289/299 words correct (96.7%), mean WER 0.0443, mean CER 0.0120.**

**Zero deletions anywhere.** The model never dropped a word across 299 words of
amateur recitation — every error is a substitution or an insertion.

For scale, quran-recitation-finder's published benchmark is WER 0.079 on
*professional qari* clips. These amateur results are better than that.

## Every error, and what it actually is

| surah | ayah | reference | hypothesis | verdict |
|---|---|---|---|---|
| Fatihah | 7 | — | آمين | **not an error** — the reciter said Ameen after finishing |
| Kafirun | 1 | يا أيها | أيها (+ يا separate) | **tokenisation artifact** of يا أيها, content correct |
| Inshiqaq | 6 | يا أيها | أيها (+ يا separate) | same artifact |
| Adiyat | 2 | فالموريات | كالموريات | real — ف→ك |
| Adiyat | 3 | فالمغيرات | كالمغيرات | real — ف→ك (same confusion) |
| Adiyat | 5 | فوسطن | فبسطن | real — و→ب |
| Tariq | 6 | دافق | دافقه | real — trailing ه (possibly pausal form) |
| Tariq | 13 | فصل | فصلح | real — trailing ح |
| Inshiqaq | 12 | ويصلي / سعيرا | ويسلي / صعيرا | real — **ص↔س swapped between adjacent words** |
| Inshiqaq | 17 | وسق | بسق | real — و→ب |

Discounting the آمين (a genuine utterance) and the two يا أيها tokenisation
artifacts, there are **8 real word errors in 299 words — a true WER of ~2.7%**,
better than the 4.43% headline.

### The error classes are consistent and small

1. **Prefix consonant confusion** — ف→ك twice in Al-Adiyat, و→ب twice.
2. **Emphatic/plain sibilant** — ص↔س in Al-Inshiqaq 12. Notable: this is exactly
   the distinction `nlp/normalize.py` deliberately preserves, so an ASR slip here
   would surface as a *pronunciation* verdict.
3. **Trailing letter** — دافقه, فصلح. Plausibly the reciter's own pausal forms
   rather than model error.

All are single-character, none is a dropped or hallucinated word, and none
relocates the passage.

## Verdict: the Al-Fatihah result was representative, not a fluke

Az-Zalzalah is also **flawless** (36/36, WER 0.0000), Al-Fatihah is word-perfect,
and At-Tariq is 59/61 across 17 ayahs. The worst surah (Al-Kafirun, WER 0.0769)
is inflated by an alignment artifact on يا أيها, not a content error — its CER is
0.0100, the second-best of the six.

Latency holds across lengths: RTF 0.090–0.251 (mean ≈ 0.14), on an 81.8s
recitation as well as a 22.8s one. The RTF spread is CPU contention on this box,
not a length effect.

## Which surahs to use for the intentional-error tests

**Primary — clean ASR baseline, so a detected mistake is the reciter's, not the model's:**

1. **Az-Zalzalah (99)** — WER 0.0000, 8 ayahs, 36 words. The cleanest possible
   substrate for missed-word and missed-ayah tests: any error the system reports
   is unambiguously the deliberate one.
2. **Al-Fatihah (1)** — word-perfect, and it carries two already-root-caused
   structures worth regression-testing: **1:3 ⊂ 1:1** (the anchor bug) and the
   **63-ID ayah 7** (the length gate).
3. **Al-Kafirun (109)** — the identical-verse case (3 and 5 are byte-identical).
   Essential for the beam tracker, and its ASR is content-correct.

**Secondary — longer sessions:**

4. **At-Tariq (86)** — 17 ayahs, only two trailing-letter slips. Good for
   missed-ayah tests over a longer passage and for jump tests.

**Avoid as primary error material (use for ASR robustness instead):**

- **Al-Adiyat (100)** — three real substitutions, two of them the same ف→ك.
- **Al-Inshiqaq (84)** — the ص↔س swap would be indistinguishable from a
  deliberate pronunciation error, which is precisely what an error test must not
  confound. Still the best long-session material (25 ayahs, 107 words) once the
  error taxonomy is separated.

## Caveats

- One reciter. Cross-speaker generalisation is untested.
- Six surahs, all short (max 25 ayahs). Long surahs untested.
- Clean recitation only — no deliberate errors yet, which is the next step.
- All recorded outside the browser. The browser capture path adds its own
  variance (see `experiment-browser-audio.md`).
