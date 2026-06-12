"""REST API: Quran text for the SPA, session lifecycle, summaries."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.db.models import Session as SessionRow
from app.db.models import SessionSummary, Surah
from app.db.repo import ayah_display, surah_list
from app.db.session import get_db
from app.ws.session import finalize_session

router = APIRouter(prefix="/api")


@router.get("/surahs")
def get_surahs(db: DBSession = Depends(get_db)):
    return surah_list(db)


@router.get("/surahs/{surah_id}/text")
def get_surah_text(surah_id: int, start_ayah: int = 1, db: DBSession = Depends(get_db)):
    if not 1 <= surah_id <= 114:
        raise HTTPException(404)
    return ayah_display(db, surah_id, start_ayah)


class CreateSession(BaseModel):
    surah_id: int | None = Field(default=None, ge=1, le=114)
    start_ayah: int = Field(default=1, ge=1)
    auto: bool = False  # auto-detect: start location-less, lock on from recitation


@router.post("/sessions")
def create_session(body: CreateSession, db: DBSession = Depends(get_db)):
    if body.auto:
        row = SessionRow(surah_id=None, start_ayah=None, status="detecting")
    else:
        if body.surah_id is None:
            raise HTTPException(422, "surah_id required unless auto=true")
        surah = db.get(Surah, body.surah_id)
        if surah is None or body.start_ayah > surah.ayah_count:
            raise HTTPException(422, "invalid surah/ayah")
        row = SessionRow(surah_id=body.surah_id, start_ayah=body.start_ayah)
    db.add(row)
    db.commit()
    return {
        "session_id": str(row.id),
        "surah_id": row.surah_id,
        "start_ayah": row.start_ayah,
        "auto": body.auto,
    }


@router.post("/sessions/{session_id}/end")
def end_session(session_id: uuid.UUID):
    finalize_session(session_id)
    return {"ok": True}


@router.get("/sessions/{session_id}/summary")
def get_summary(session_id: uuid.UUID, db: DBSession = Depends(get_db)):
    row = db.get(SessionRow, session_id)
    if row is None:
        raise HTTPException(404)
    summary = db.get(SessionSummary, session_id)
    return {
        "session_id": str(session_id),
        "surah_id": row.surah_id,
        "start_ayah": row.start_ayah,
        "status": row.status,
        "summary": None
        if summary is None
        else {
            "duration_sec": summary.duration_sec,
            "words_ok": summary.words_ok,
            "words_missed": summary.words_missed,
            "ayahs_missed": summary.ayahs_missed,
            "jumps": summary.jumps,
            "errors": summary.detail.get("errors", []),
        },
    }
