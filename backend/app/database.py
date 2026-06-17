"""
Ghaf App — database session/engine setup.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from .config import get_settings
from .models import Base

settings = get_settings()

connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Create all tables. Suitable for dev/demo; use Alembic migrations in production."""
    Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
