# FastConformer on an amateur voice (2026-09-04)

The decisive test from the comparison doc: their benchmark is on a professional
qari, which is the population we *already* handle. Does their ASR hold up on the
amateur voice our phoneme tracker fails on?

Setup: `mohammed/fastconformer-quran-ar`, checkpoint
`phase3_full/phase3_full_wer0.0014.nemo`, NeMo 3.0.0 + torch 2.14 CPU, installed
in an isolated venv — **production untouched**.

## Result

Input: the user's own 31.0s Al-Fatihah recitation (`/root/temp/fatiha.ogg`), the
same audio our phoneme tracker scores at CER 0.45–0.50 against references.

```
بِسْمِ اللَّهِ الرَّحْمَنِ الرَّحِيمِ الْحَمْدُ لِلَّهِ رَبِّ الْعَالَمِينَ الرَّحْمَنِ الرَّحِيمِ
مَالِكِ يَوْمِ الدِّينِ إِيَّاكَ نَعْبُدُ وَإِيَّاكَ نَسْتَعِينُ اهدِنَا الصِّرَاطَ الْمُسْتَقِيمَ
صِرَاطَ الَّذِينَ أَنْعَمْتَ عَلَيْهِمْ غَيْرِ الْمَغْضُوبِ عَلَيْهِمْ وَلا الضَّالِّينَ آمين
```

| | words | WER | CER |
|---|---|---|---|
| as spoken (includes آمين) | 30/29 | 0.0345 | 0.0272 |
| **آمين removed** (not part of the surah) | **29/29** | **0.0000** | **0.0000** |

**A perfect transcription of all seven ayahs.** The only difference from the
canonical text is the *آمين* the reciter genuinely said after finishing — an
accurate transcription of what was uttered, not a hallucination.

Latency: 3633 ms for 31.0 s of audio, CPU, RTF ≈ 0.12 — comparable to our current
pipeline (which spends ~1.4 s on a 5 s window).

## What this means

The accuracy problem was **never the reciter, the microphone, the browser audio
path, or the segmentation.** Those investigations each found something real, but
none of them was the main cause. The cause is that our encoder-CTC phoneme model
is simply much weaker than this Quran-fine-tuned FastConformer on non-professional
recitation.

Every prior hypothesis is now in proportion:

| finding | real? | was it the main cause? |
|---|---|---|
| one-ayah-per-window | yes, fixed | no |
| Husary-only references | yes | no — professionals cluster within 0.11 CER |
| browser WebRTC processing | yes, ~consistency | no — best ON take reached 6/7 |
| sub-ayah fragmentation | yes, fixed | no — failing windows were ayah-sized |
| 1:3 ⊂ 1:1 anchor bug | yes, fixed | no — a symptom, not the cause |
| ayah 7 length gate | yes, fixed | no |
| **weak ASR model** | **yes** | **yes** |

## The fork this opens

FastConformer outputs **text**, not phoneme IDs. Adopting it means matching text
against the Quran — which is what our **Whisper path already does**
(`ws/session.py`, `engine/aligner.py`, `engine/detector.py`, the mutashabeh
index). That path already has word-level tracking, MISSED_WORD, and the
provisional/confirmed/revoked lifecycle the phoneme tracker never gained.

So this is not a rewrite. It is plausibly **swapping the ASR engine underneath the
Whisper path we already built and then abandoned** — the path was abandoned
because whisper-base was fragile on amateur mics, and that premise no longer
holds with a model that transcribes this voice at WER 0.0000.

Word-level detection would also come back, which phoneme v1 explicitly gave up
(no MISSED_WORD, whole-ayah granularity only).

## Caveats before committing to the fork

- **n = 1 amateur recording, one surah, one reciter.** The effect size is
  unambiguous but this is not a corpus. Al-Fatihah is also the most-recited surah
  in existence and likely the best represented in any Quran ASR training set —
  the model may be weaker on less common passages.
- **NeMo is a heavy dependency**: ~2.2 GB venv, plus a 460 MB checkpoint on top of
  the 352 MB phoneme model. Python 3.11/3.12 only.
- **Latency under concurrency is unmeasured**, and RNN-T decoding is a step loop.
- Our Whisper path's aligner and detector have not been exercised in months and
  were tuned against whisper-base output, not FastConformer output.

## Recommended next step

Test FastConformer on a **less common surah** and on a deliberately-erroneous
recitation before deciding. If it holds, plan the engine swap into the Whisper
path rather than continuing to patch the phoneme tracker.
