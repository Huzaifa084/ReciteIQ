"""Typed detection events — the contract between engine, WS layer, and SPA (D13).

Lifecycle: events are born `provisional` (paint immediately), become `confirmed`
once the engine is sure, or `revoked` if later evidence contradicts them
(e.g. a jump banner withdrawn, a missed word re-recited after a REWIND).
The frontend reducer keys on `event_id` to apply state transitions.
"""

import itertools
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

_event_counter = itertools.count(1)


class EventType(StrEnum):
    WORD_OK = "WORD_OK"                  # payload: word ref (surah, ayah, position, global_idx)
    MISSED_WORD = "MISSED_WORD"          # payload: word ref
    MISSED_AYAH = "MISSED_AYAH"          # payload: surah, ayah (expected), resumed_at
    MUTASHABEH_JUMP = "MUTASHABEH_JUMP"  # payload: dest surah/ayah, score
    REPEAT = "REPEAT"                    # benign rewind (D2); payload: from/to position
    PREAMBLE = "PREAMBLE"                # isti'adha/basmalah consumed (D7); payload: kind
    POSITION = "POSITION"                # current pointer for UI/resume; payload: word ref


class EventState(StrEnum):
    PROVISIONAL = "provisional"
    CONFIRMED = "confirmed"
    REVOKED = "revoked"


@dataclass
class Event:
    type: EventType
    state: EventState
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: int = field(default_factory=lambda: next(_event_counter))
    refers_to: int | None = None  # event_id this confirms/revokes

    def to_dict(self) -> dict[str, Any]:
        d = {
            "event_id": self.event_id,
            "type": self.type.value,
            "state": self.state.value,
            "payload": self.payload,
        }
        if self.refers_to is not None:
            d["refers_to"] = self.refers_to
        return d
