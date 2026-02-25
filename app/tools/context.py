from __future__ import annotations

from contextvars import ContextVar

from sqlalchemy.orm import Session

current_session_id: ContextVar[str | None] = ContextVar("current_session_id", default=None)
current_db_session: ContextVar[Session | None] = ContextVar("current_db_session", default=None)


def get_current_session_id() -> str | None:
    return current_session_id.get()


def set_current_session_id(session_id: str) -> object:
    return current_session_id.set(session_id)


def reset_current_session_id(token: object) -> None:
    current_session_id.reset(token)


def get_current_db_session() -> Session | None:
    return current_db_session.get()


def set_current_db_session(db: Session) -> object:
    return current_db_session.set(db)


def reset_current_db_session(token: object) -> None:
    current_db_session.reset(token)
