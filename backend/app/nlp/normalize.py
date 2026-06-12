"""Arabic normalization for matching ASR output against the reference text.

Input is *standard-orthography* (Imlaei) Arabic — either the reference word's
`text_imlaei` or a raw ASR transcript. Output is a diacritic-free, variant-
harmonized matching key. Both sides of every comparison MUST pass through
normalize() so they meet in the same canonical space.

Deliberately NOT handled here: Uthmani rasm differences (الصلوة vs الصلاة) —
those are solved at the data layer by matching on Imlaei text (decision D1),
not by normalization rules.
"""

import re
import unicodedata

# Tashkeel/diacritics: fathatan..sukun range, superscript alef, quranic annotation marks
_DIACRITICS = re.compile(
    "["
    "ؐ-ؚ"   # honorific/quranic signs
    "ً-ٟ"   # tashkeel (fathatan .. wavy hamza below)
    "ٰ"          # superscript (dagger) alef
    "ۖ-ۜ"   # small high ligatures / stop signs
    "۟-ۨ"   # small high marks
    "۪-ۭ"   # empty centre marks
    "ـ"          # tatweel
    "]"
)

_ALEF_VARIANTS = re.compile("[آأإٱ]")  # آ أ إ ٱ -> ا
_YA_VARIANTS = re.compile("[ى]")                       # ى (alef maqsura) -> ي
_WAW_HAMZA = re.compile("[ؤ]")                         # ؤ -> و
_YA_HAMZA = re.compile("[ئ]")                          # ئ -> ي
_TA_MARBUTA = re.compile("[ة]")                        # ة -> ه
_NON_ARABIC = re.compile(r"[^ء-ي\s]")             # drop anything outside core Arabic block


def normalize(text: str) -> str:
    """Canonical matching form: NFC, no diacritics, harmonized letter variants."""
    text = unicodedata.normalize("NFC", text)
    text = _DIACRITICS.sub("", text)
    text = _ALEF_VARIANTS.sub("ا", text)
    text = _WAW_HAMZA.sub("و", text)
    text = _YA_HAMZA.sub("ي", text)
    text = _YA_VARIANTS.sub("ي", text)
    text = _TA_MARBUTA.sub("ه", text)
    text = _NON_ARABIC.sub("", text)
    return " ".join(text.split())


def tokenize(text: str) -> list[str]:
    """Normalize then split into word tokens (drops empties)."""
    return [t for t in normalize(text).split(" ") if t]
