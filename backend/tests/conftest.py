"""Shared fixtures. The Quran tables are static, verified data (load_quran.py),
so engine tests run against the real reference text from the local Postgres —
this is deliberate: hand-rolled fake ayahs would hide orthography bugs."""

import pytest

from app.db.repo import load_reference
from app.db.session import SessionLocal


@pytest.fixture(scope="session")
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture(scope="session")
def ref_fatiha(db):
    return load_reference(db, 1)  # Al-Fatiha (basmalah IS ayah 1)


@pytest.fixture(scope="session")
def ref_ikhlas(db):
    return load_reference(db, 112)


@pytest.fixture(scope="session")
def ref_tawbah(db):
    return load_reference(db, 9)  # no basmalah


@pytest.fixture(scope="session")
def ref_rahman(db):
    return load_reference(db, 55)  # the 31x refrain


def tokens_of(ref, ayah: int) -> list[str]:
    """Normalized tokens of one ayah straight from the reference (perfect ASR)."""
    return [w.norm for w in ref if w.ayah == ayah]
