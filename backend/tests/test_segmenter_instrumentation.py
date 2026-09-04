"""P1-7: the segmenter must report WHY a window closed, so the
smart-cut-vs-overlap question can be settled with data (plan §1, §P2-5)."""

import numpy as np

from app.audio.vad import Segment, StreamSegmenter


def test_segment_defaults_to_silence_reason():
    seg = Segment(audio=np.zeros(4, dtype=np.float32), starts_with_overlap=False, duration=0.1)
    assert seg.closed_reason == "silence"


def test_flush_is_labelled_flush():
    seg = StreamSegmenter(max_sec=2.0, silence_cut_sec=0.3)
    seg._buf = np.ones(16000, dtype=np.float32) * 0.1   # pretend a second of speech
    seg._had_speech = True
    out = seg.flush()
    assert out is not None and out.closed_reason == "flush"


def test_forced_cut_reasons_are_distinguished():
    """A cap-driven cut is labelled max_smart when it lands on a quiet point and
    max_hard when it slices mid-speech — the two have different CER consequences."""
    seg = StreamSegmenter(max_sec=1.0, silence_cut_sec=0.3)
    seg._buf = np.ones(16000, dtype=np.float32) * 0.1
    seg._had_speech = True
    seg._quiet_pos = -1                      # no quiet point → hard cut
    assert seg._cut(forced=True).closed_reason == "max_hard"

    seg2 = StreamSegmenter(max_sec=1.0, silence_cut_sec=0.3)
    seg2._buf = np.ones(16000, dtype=np.float32) * 0.1
    seg2._had_speech = True
    seg2._quiet_pos = 15000                  # recent quiet point → smart cut
    assert seg2._cut(forced=True).closed_reason == "max_smart"
