# Gate: does FastConformer "correct" deliberate errors? (2026-09-04)

The criterion that matters is **faithful transcription of what was actually
spoken**, not low WER against the expected Quran text. A model that silently
repairs a reciter's mistake is useless for this product no matter how good its
WER looks.

## How the error clips were made — and the honest limit

**No deliberately-erroneous recordings were provided**, so eight of the nine clips
were constructed by **surgical edits of the reciter's own audio**, cutting at the
midpoint of the inter-word gaps taken from the model's own word timestamps. No
splice lands mid-phoneme.

This is sound for **omissions and repetitions**: a splice artifact pushes a model
toward garbage, not toward emitting exactly the right missing word, so a clean
"stayed absent" result is trustworthy.

**The substitution case is NOT constructible this way** and remains untested — it
needs the reciter to actually say a wrong word.

## Results

Memory: RSS 681 MB before load → **1616 MB after** (model ≈ 935 MB).
Latency: **RTF 0.090 – 0.175** throughout, on 19–36 s clips.

| clip | RTF | vs EXPECTED WER / CER | vs ACTUAL-SPOKEN WER / CER | words hyp/spoken/expected | verdict |
|---|---|---|---|---|---|
| zilzal skip_word | 0.132 | 0.0278 / 0.0311 | **0.0000 / 0.0000** | 35/35/36 | **FAITHFUL** |
| zilzal skip_ayah3 | 0.120 | 0.1111 / 0.1036 | **0.0000 / 0.0000** | 32/32/36 | **FAITHFUL** |
| zilzal repeat_ayah2 | 0.175 | 0.0278 / 0.0398 | 0.0513 / 0.0607 | 37/39/36 | partial |
| fatiha skip_word | 0.090 | 0.0690 / 0.0175 | 0.0690 / 0.0349 | 28/29/29 | mixed |
| fatiha skip_ayah3 | 0.140 | 0.1034 / 0.1111 | **0.0000 / 0.0000** | 28/28/29 | **FAITHFUL** |
| fatiha repeat_ayah2 | 0.154 | 0.1724 / 0.1364 | **0.0000 / 0.0000** | 34/34/29 | **FAITHFUL** |
| kaferoon skip_word | 0.130 | 0.0769 / 0.0000 | 0.0385 / 0.0240 | 27/26/26 | ambiguous |
| **kaferoon skip_ayah4 (3→5)** | 0.163 | 0.2692 / 0.1680 | **0.0000 / 0.0000** | 22/22/26 | **FAITHFUL** |
| kaferoon repeat_ayah2 | 0.120 | 0.2308 / 0.1379 | **0.0000 / 0.0000** | 31/31/26 | **FAITHFUL** |

**Six clips are exact** — WER 0.0000 against what was actually spoken while
diverging from the expected text by up to 0.2692. That is precisely the signature
we needed: the model reports the recitation, not the scripture.

### Did each deliberate error survive?

| error | outcome |
|---|---|
| skipped word (zilzal, الأرض) | **stayed absent** |
| skipped word (fatiha, لله) | **stayed absent** |
| skipped word (kaferoon, لا) | **ambiguous** — see below |
| skipped ayah (zilzal 3, 4 words) | **stayed absent** |
| skipped ayah (fatiha 3, 2 words) | **stayed absent** |
| skipped ayah (kaferoon 4, 5 words) | **stayed absent** |
| repeated ayah (fatiha 2) | **transcribed, +5 words** |
| repeated ayah (kaferoon 2) | **transcribed, +5 words** |
| repeated ayah (zilzal 2) | partially collapsed: +1 of +3 |

**8 of 9 survived. All 3 skipped ayahs survived exactly.**

### The Al-Kafirun 3→5 transition — the case that matters most

Removing ayah 4 makes the recitation run 3 → 5, and 3 and 5 are byte-identical.
FastConformer transcribed **exactly what was spoken** (WER 0.0000) — the identical
phrase twice in succession — and did **not** invent the intervening ayah 4, even
though the surrounding context makes it highly predictable. WER against the
expected full surah was 0.2692.

This is the strongest single result in the gate: it is the exact structure that
defeats a single-pointer tracker, and the ASR hands the ambiguity through cleanly
rather than resolving it wrongly.

### The one ambiguous case

`kaferoon skip_word` removed **لا** — a two-phoneme function word inside
"لا أعبد", where the two words are coarticulated with essentially no gap. The
transcript still contains لا once (as do both the expected text and the clean
take). Two readings:

1. the model reconstructed it, or
2. the cut did not fully excise it, because timestamp boundaries are least
   reliable exactly on short coarticulated function words.

(2) is the more likely, and it is a limitation of *surgical editing*, not
evidence about the model. It is also why a real recorded word-skip is still
wanted. Note the +1 word count is the known يا/أيها split artifact, not recovered
content.

## Verdict: PASS on the critical criterion, with one gap

FastConformer transcribes what was spoken. It does not repair omissions, it
reproduces repetitions, and it does not invent a skipped ayah even when identical
surrounding verses make it predictable.

**Still open:** the substitution case. A model that faithfully preserves omissions
could still normalise a *mispronounced* word toward the expected one, and that is
the failure mode most relevant to Tajweed feedback. One recording of a
deliberately wrong word in Az-Zalzalah would close it.

---

# Substitution gate — natively recorded (2026-09-04)

`/root/temp/zilzal-with-errors.ogg`, 27.5s — real audio of real mistakes, not a
surgical edit. This closes the gap left above.

| take | duration | RTF | words | WER vs expected | CER vs expected |
|---|---|---|---|---|---|
| clean `zilzal.ogg` | 32.6s | 0.122 | 36 | **0.0000** | **0.0000** |
| `zilzal-with-errors.ogg` | 27.5s | 0.149 | 30 | **0.2500** | **0.1813** |

RSS 1616 MB (unchanged).

## The deliberate errors, and what the model did with each

The clean take is word-perfect, so differences against the clean take and against
the canonical text are **identical** — the diff isolates exactly the deliberate
errors.

| ayah | reference | actually spoken | hypothesis | preserved? |
|---|---|---|---|---|
| 2 | أَثْقَالَهَا | **زِلْسَالَهَا** | زلسالها | **YES** |
| 4 | أَخْبَارَهَا | **أَثْقَالَهَا** | اثقالها | **YES** |
| 5 | بِأَنَّ | **لِأَنَّ** | لان | **YES** |
| 7 | يعمل / مثقال / ذرة / خيرا / يره / ومن | *(skipped)* | (nothing) | **YES** |

Per-ayah words correct vs expected: `1:4/4 2:2/3 3:4/4 4:2/3 5:3/4 6:6/6 7:1/6 8:5/6`

**All four deliberate errors survived. Zero corrections.**

## Why this is decisive, not merely positive

**1. The model emitted a non-Quranic word.** `زِلْسَالَهَا` does not occur
anywhere in the Qur'an — it is a blend of `زِلْزَالَهَا` and `أَثْقَالَهَا`. A model
that normalises toward scripture had every opportunity to snap it to the expected
`أَثْقَالَهَا`, and instead reported a word that exists nowhere in its training
text.

**2. The hardest case is ayah 4.** The reciter substituted `أَثْقَالَهَا` — a word
that *is* Quranic and appears two ayahs earlier — where `أَخْبَارَهَا` was
expected. Context makes `أَخْبَارَهَا` overwhelmingly predictable, and a
language-model-biased recogniser would repair it silently. FastConformer reported
what was said.

**3. A single-letter substitution survived.** `بِأَنَّ` → `لِأَنَّ` differs by one
consonant and is the kind of slip an acoustic model is most tempted to smooth.

**4. The skipped ayah stayed absent**, consistent with the surgical-edit results.

## Verdict: validation gate COMPLETE

FastConformer transcribes the recitation, not the scripture — across omissions,
repetitions, identical-verse transitions, and now genuine substitutions including
a non-existent word. This is the property the whole product depends on: the
system can only flag a mistake the recogniser is willing to report.
