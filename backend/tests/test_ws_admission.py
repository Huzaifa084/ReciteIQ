"""Admission control and client identification.

This file exists because `session.py` had no tests at all, and three of the five
critical audit findings lived in it. Admission is exercised directly against the
registry and the header logic rather than through a live server, so it runs in
milliseconds and in CI.
"""

import asyncio

import pytest

from app.config import settings
from app.ws.session import SessionRegistry, client_ip


class _FakeWS:
    """Only what client_ip reads: the peer address and the headers."""

    def __init__(self, peer: str, headers: dict | None = None):
        self.client = type("C", (), {"host": peer})()
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}


# ------------------------------------------------------------------ client ip


def test_forwarded_header_is_believed_from_the_compose_proxy():
    """The real bug: every visitor arrived as the nginx container address, so
    the per-IP cap became a global cap of 2 for the whole site."""
    ws = _FakeWS("172.24.0.4", {"X-Forwarded-For": "203.0.113.7"})
    assert client_ip(ws) == "203.0.113.7"


def test_two_visitors_behind_the_proxy_are_told_apart():
    a = _FakeWS("172.24.0.4", {"X-Forwarded-For": "203.0.113.7"})
    b = _FakeWS("172.24.0.4", {"X-Forwarded-For": "198.51.100.22"})
    assert client_ip(a) != client_ip(b)


def test_forwarded_header_is_ignored_from_an_untrusted_peer():
    """Otherwise any client lifts its own cap by inventing the header."""
    ws = _FakeWS("203.0.113.9", {"X-Forwarded-For": "10.9.9.9"})
    assert client_ip(ws) == "203.0.113.9"


def test_only_the_left_most_forwarded_entry_is_used():
    ws = _FakeWS("172.24.0.4", {"X-Forwarded-For": "203.0.113.7, 172.24.0.4"})
    assert client_ip(ws) == "203.0.113.7"


def test_a_malformed_forwarded_header_degrades_to_the_peer():
    """A garbage header must not become an unbounded bucket key."""
    ws = _FakeWS("172.24.0.4", {"X-Forwarded-For": "not-an-ip"})
    assert client_ip(ws) == "172.24.0.4"


def test_no_header_uses_the_peer():
    assert client_ip(_FakeWS("203.0.113.5")) == "203.0.113.5"


# ------------------------------------------------------------------ admission


async def test_distinct_clients_are_admitted_independently():
    """The behaviour B-3 broke: two different people must both get in."""
    r = SessionRegistry()
    assert await r.try_admit("s1", "203.0.113.7") is None
    assert await r.try_admit("s2", "198.51.100.22") is None
    assert len(r.active) == 2


async def test_per_client_cap_still_binds():
    r = SessionRegistry()
    ip = "203.0.113.7"
    for i in range(settings.max_sessions_per_ip):
        assert await r.try_admit(f"s{i}", ip) is None
    assert await r.try_admit("over", ip) == "too many sessions from this device"


async def test_per_client_cap_is_never_tighter_than_the_global_cap():
    """The shape of B-3: when per-IP is the tighter number AND the client
    address is unknowable behind an L4 proxy, it silently becomes a global cap.
    """
    assert settings.max_sessions_per_ip <= settings.max_concurrent_sessions


async def test_global_cap_still_binds_across_distinct_clients():
    r = SessionRegistry()
    for i in range(settings.max_concurrent_sessions):
        assert await r.try_admit(f"s{i}", f"203.0.113.{i + 1}") is None
    assert await r.try_admit("overflow", "203.0.113.200") == "busy"


async def test_duplicate_session_id_is_refused():
    r = SessionRegistry()
    assert await r.try_admit("same", "203.0.113.7") is None
    assert await r.try_admit("same", "198.51.100.22") == "session already connected"


async def test_concurrent_admits_cannot_exceed_the_global_cap():
    """B-10: the slot used to be reserved AFTER the cap check, so simultaneous
    connects could all pass before any of them inserted."""
    r = SessionRegistry()
    results = await asyncio.gather(*(
        r.try_admit(f"s{i}", f"203.0.113.{i + 1}") for i in range(12)
    ))
    admitted = [x for x in results if x is None]
    assert len(admitted) == settings.max_concurrent_sessions
    assert len(r.active) == settings.max_concurrent_sessions


async def test_release_frees_both_the_slot_and_the_client_budget():
    r = SessionRegistry()
    ip = "203.0.113.7"
    await r.try_admit("s1", ip)
    await r.try_admit("s2", ip)
    await r.release("s1", ip)
    assert await r.try_admit("s3", ip) is None
    await r.release("s2", ip); await r.release("s3", ip)
    assert r.active == {} and dict(r.per_ip) == {}


async def test_more_than_two_visitors_can_recite_at_once():
    """The user-visible symptom: the third visitor was turned away."""
    r = SessionRegistry()
    for i in range(3):
        assert await r.try_admit(f"s{i}", f"203.0.113.{i + 1}") is None, \
            f"visitor {i + 1} was rejected"
