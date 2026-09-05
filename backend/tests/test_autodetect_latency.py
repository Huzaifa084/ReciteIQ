"""Auto-detect must not wait for a tracking window.

Reported from the browser: 30-40 seconds before a location was found. Measured
cause: detection cannot resolve before the first segment CLOSES, and with the
25 s tracking window on continuously-recited audio that is 25-28 s. Detection
needs a rough location from a handful of words, not an accurate transcript.
"""

import uuid

import pytest

from app.config import Settings, settings

# The shipped configuration. These tests are about the production path, and the
# local default engine (whisper_local) uses the SAME window for tracking as the
# detection window, which would make the comparison vacuously false rather than
# meaningfully true.
PROD = Settings(asr_engine="fastconformer")
from app.db.models import Session as SessionRow
from app.db.session import SessionLocal
from app.ws.session import LiveSession


@pytest.fixture
def guided_session():
    sid = uuid.uuid4()
    s = SessionLocal()
    try:
        s.add(SessionRow(id=sid, surah_id=112, start_ayah=1, status="active"))
        s.commit()
    finally:
        s.close()
    yield sid
    s = SessionLocal()
    try:
        s.query(SessionRow).filter_by(id=sid).delete()
        s.commit()
    finally:
        s.close()


def test_detecting_session_segments_short():
    """No surah chosen yet: segment for speed."""
    live = LiveSession(uuid.uuid4(), None, None)
    assert live.tracker is None and live.detector is not None
    window = live.segmenter._max_samples / settings.sample_rate
    assert window == settings.detect_segment_max_sec


def test_detection_window_is_shorter_than_the_shipped_tracking_window():
    """The property that fixes the 30-40 s wait, checked against the config that
    actually ships rather than whatever the local default happens to be."""
    assert PROD.detect_segment_max_sec < PROD.segment_max_sec, (
        f"detection window {PROD.detect_segment_max_sec}s is not shorter than the "
        f"{PROD.segment_max_sec}s tracking window — the wait comes back"
    )


def test_guided_session_segments_for_tracking(guided_session):
    """A surah was chosen, so there is nothing to detect — track accurately."""
    live = LiveSession(guided_session, 112, 1)
    window = live.segmenter._max_samples / settings.sample_rate
    assert window == settings.segment_max_sec


def test_locking_restores_the_tracking_window(guided_session):
    """Detection traded transcript quality for speed. Tracking needs the
    opposite: the release gate measured five false missed words at 5 s windows
    where 25 s produced none, so the wide window must come back on lock."""
    live = LiveSession(uuid.uuid4(), None, None)
    assert live.segmenter._max_samples / settings.sample_rate == settings.detect_segment_max_sec

    live.id = guided_session          # lock_location writes the row
    live.lock_location(112, 1)

    assert live.tracker is not None and live.detector is None
    assert live.segmenter._max_samples / settings.sample_rate == settings.segment_max_sec, (
        "tracking must not continue on the detection window"
    )


def test_the_detection_window_is_actually_faster():
    """Guards the property, not the constant: someone raising
    detect_segment_max_sec to the tracking window would silently restore the
    30-40 s wait."""
    assert settings.detect_segment_max_sec <= 8.0, (
        "a detection window this wide reintroduces the latency it exists to fix"
    )
