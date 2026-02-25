from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings


def _ensure_sqlite_directory(database_url: str) -> None:
    if not database_url.startswith("sqlite:///"):
        return

    raw_path = database_url.replace("sqlite:///", "", 1)
    if not raw_path or raw_path == ":memory:":
        return

    decoded_path = unquote(raw_path)
    db_path = Path(decoded_path)
    if not db_path.is_absolute():
        db_path = Path.cwd() / db_path

    db_path.parent.mkdir(parents=True, exist_ok=True)

Base = declarative_base()
_ensure_sqlite_directory(settings.database_url)
engine = create_engine(settings.database_url, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    from app.domain import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
