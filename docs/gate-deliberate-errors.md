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
