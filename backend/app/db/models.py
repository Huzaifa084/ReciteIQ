"""SQLAlchemy models.

Word rows are dual-script (decision D1): `text_uthmani` is what the UI renders,
`text_normalized` (derived from Imlaei/standard orthography) is what the aligner
matches ASR output against. Never match against Uthmani-derived text.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Surah(Base):
    __tablename__ = "surahs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # 1..114
    name_arabic: Mapped[str] = mapped_column(String(64))
    name_english: Mapped[str] = mapped_column(String(64))
    ayah_count: Mapped[int] = mapped_column(Integer)

    ayahs: Mapped[list["Ayah"]] = relationship(back_populates="surah", order_by="Ayah.number")


class Ayah(Base):
    __tablename__ = "ayahs"
    __table_args__ = (
        UniqueConstraint("surah_id", "number", name="uq_ayah_surah_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # 1..6236 (global ayah index)
    surah_id: Mapped[int] = mapped_column(ForeignKey("surahs.id"))
    number: Mapped[int] = mapped_column(Integer)                # 1-based within surah
    verse_key: Mapped[str] = mapped_column(String(8), unique=True, index=True)  # "2:255"
    text_uthmani: Mapped[str] = mapped_column(Text)             # full ayah, display convenience

    surah: Mapped[Surah] = relationship(back_populates="ayahs")
    words: Mapped[list["Word"]] = relationship(back_populates="ayah", order_by="Word.position")


class Word(Base):
    __tablename__ = "words"
    __table_args__ = (
        UniqueConstraint("ayah_id", "position", name="uq_word_ayah_position"),
        Index("ix_words_ayah_position", "ayah_id", "position"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # canonical QUL word id
    ayah_id: Mapped[int] = mapped_column(ForeignKey("ayahs.id"))
    position: Mapped[int] = mapped_column(Integer)                 # 1-based within ayah
    text_uthmani: Mapped[str] = mapped_column(String(64))          # display script
    text_imlaei: Mapped[str] = mapped_column(String(64))           # standard orthography (source)
    text_normalized: Mapped[str] = mapped_column(String(64), index=True)  # matching key

    ayah: Mapped[Ayah] = relationship(back_populates="words")


class MutashabehPair(Base):
    """Precomputed lexically-similar ayah pairs (offline n-gram build, D6)."""

    __tablename__ = "mutashabeh_pairs"
    __table_args__ = (
        UniqueConstraint("source_ayah_id", "target_ayah_id", name="uq_mutashabeh_pair"),
        Index("ix_mutashabeh_source", "source_ayah_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_ayah_id: Mapped[int] = mapped_column(ForeignKey("ayahs.id"))
    target_ayah_id: Mapped[int] = mapped_column(ForeignKey("ayahs.id"))
    score: Mapped[float] = mapped_column(Float)  # n-gram Jaccard/containment, 0..1


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)  # auth later
    # Nullable: auto-detect sessions start location-less; filled once detected
    surah_id: Mapped[int | None] = mapped_column(ForeignKey("surahs.id"), nullable=True)
    start_ayah: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="created")  # created|detecting|active|ended
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SessionEvent(Base):
    """Raw detection event log. Anonymous rows are purged after retention (D11);
    the summary page reads SessionSummary, never this table."""

    __tablename__ = "session_events"
    __table_args__ = (Index("ix_events_session_ts", "session_id", "ts"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    type: Mapped[str] = mapped_column(String(32))   # WORD_OK | MISSED_WORD | MISSED_AYAH | ...
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)


class SessionSummary(Base):
    __tablename__ = "session_summaries"

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True
    )
    duration_sec: Mapped[float] = mapped_column(Float, default=0.0)
    words_ok: Mapped[int] = mapped_column(Integer, default=0)
    words_missed: Mapped[int] = mapped_column(Integer, default=0)
    ayahs_missed: Mapped[int] = mapped_column(Integer, default=0)
    jumps: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)  # per-error positions for the summary view
