"""Auto-detection hard cases: unique opening, ambiguous opening, preamble."""

import pytest

from app.engine.locate import LocationDetector
from app.engine.detector import BASMALAH, ISTIADHA
from app.mutashabeh.index import get_relocation_index
from tests.conftest import tokens_of


@pytest.fixture(scope="session")
def index():
    return get_relocation_index()


def test_unique_opening_detected(index, ref_ikhlas):
    det = LocationDetector(index)
    loc = det.feed(tokens_of(ref_ikhlas, 1))  # قل هو الله احد
    assert loc is not None and loc.surah == 112 and loc.ayah == 1


def test_ambiguous_opening_waits_then_resolves(index, ref_fatiha):
    # الحمد لله رب العالمين is genuinely ambiguous — it opens 1:2 but also ends
    # 10:10, 37:182, 39:75 and 40:65 verbatim. The detector must keep waiting
    # through the WHOLE ayah and only lock once ayah 3 disambiguates the run.
    det = LocationDetector(index)
    assert det.feed(tokens_of(ref_fatiha, 2)) is None  # still ambiguous!
    loc = det.feed(tokens_of(ref_fatiha, 3))           # الرحمن الرحيم continues
    assert loc is not None and loc.surah == 1 and loc.ayah == 2


def test_preamble_stripped_before_detection(index, ref_ikhlas):
    det = LocationDetector(index)
    assert det.feed(list(ISTIADHA)) is None
    assert det.feed(list(BASMALAH)) is None
    loc = det.feed(tokens_of(ref_ikhlas, 1))
    assert loc is not None and loc.surah == 112 and loc.ayah == 1
    # replay tokens exclude the preamble
    assert det.tokens == tokens_of(ref_ikhlas, 1)


def test_fatiha_via_basmalah_locks_ayah_2(index, ref_fatiha):
    # Reciting Fatiha from the top: basmalah consumed as preamble, ayah 2 alone
    # is ambiguous (see above), ayah 3 locks detection at 1:2.
    det = LocationDetector(index)
    assert det.feed(tokens_of(ref_fatiha, 1)) is None  # basmalah = preamble
    assert det.feed(tokens_of(ref_fatiha, 2)) is None  # ambiguous with 10:10 etc.
    loc = det.feed(tokens_of(ref_fatiha, 3))
    assert loc is not None and loc.surah == 1 and loc.ayah == 2


def test_mid_surah_start_detected(index, ref_rahman):
    # Hifz revision often starts mid-surah; ayah 26 (كل من عليها فان) is unique
    det = LocationDetector(index)
    toks = tokens_of(ref_rahman, 26) + tokens_of(ref_rahman, 27)
    loc = det.feed(toks)
    assert loc is not None and loc.surah == 55
    assert 25 <= loc.ayah <= 27
