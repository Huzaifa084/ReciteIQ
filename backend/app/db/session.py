"""Engine/session factory. Sync SQLAlchemy is fine: DB work is tiny (reads of
static Quran text, batched event writes); the hot path is CPU-bound ASR."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, pool_size=5, max_overflow=5)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
