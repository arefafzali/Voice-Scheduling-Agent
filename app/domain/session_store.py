from __future__ import annotations

from threading import RLock
from typing import Dict

from app.domain.schemas import SessionState


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: Dict[str, SessionState] = {}
        self._lock = RLock()

    def create(self, timezone: str, duration_minutes: int) -> SessionState:
        with self._lock:
            state = SessionState(timezone=timezone, duration_minutes=duration_minutes)
            self._sessions[state.session_id] = state
            return state

    def get(self, session_id: str) -> SessionState:
        with self._lock:
            if session_id not in self._sessions:
                raise KeyError(session_id)
            return self._sessions[session_id]

    def save(self, state: SessionState) -> None:
        with self._lock:
            self._sessions[state.session_id] = state
