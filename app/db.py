from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote

from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

# from app.domain.models import oauth_tokens, audit_logs   # noqa: F401
from app.db_base import Base

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

# Base = declarative_base()
_ensure_sqlite_directory(settings.database_url)
engine = create_engine(settings.database_url, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
CURRENT_SCHEMA_VERSION = 1


def _ensure_migration_table() -> None:
    statement = text(
        """
        CREATE TABLE IF NOT EXISTS app_schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    with engine.begin() as connection:
        connection.execute(statement)


def _current_version() -> int | None:
    with engine.begin() as connection:
        row = connection.execute(
            text("SELECT version FROM app_schema_migrations ORDER BY version DESC LIMIT 1")
        ).fetchone()
        if row is None:
            return None
        return int(row[0])


def _write_schema_version(version: int) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO app_schema_migrations (version, applied_at) VALUES (:version, CURRENT_TIMESTAMP)"
            ),
            {"version": version},
        )


def migrate_db() -> None:
    """Apply schema creation and stamp the current schema version."""
    from app.domain import models  # noqa: F401

    _ensure_migration_table()
    Base.metadata.create_all(bind=engine)
    version = _current_version()
    if version is None or version < CURRENT_SCHEMA_VERSION:
        _write_schema_version(CURRENT_SCHEMA_VERSION)


def init_db() -> None:
    """Initialize database schema according to startup migration strategy."""
    from app.domain import models  # noqa: F401

    _ensure_migration_table()
    version = _current_version()

    if version is None:
        if settings.db_require_migrations:
            raise RuntimeError(
                "Database schema is not initialized. Run migrations before starting in prod mode."
            )
        Base.metadata.create_all(bind=engine)
        _write_schema_version(CURRENT_SCHEMA_VERSION)
        return

    if version < CURRENT_SCHEMA_VERSION:
        if settings.db_require_migrations:
            raise RuntimeError(
                f"Database schema version {version} is behind {CURRENT_SCHEMA_VERSION}. "
                "Run migrations before starting in prod mode."
            )
        Base.metadata.create_all(bind=engine)
        _write_schema_version(CURRENT_SCHEMA_VERSION)


if __name__ == "__main__":
    migrate_db()
