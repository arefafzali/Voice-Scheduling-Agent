from __future__ import annotations

from typing import Any, Dict

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.adapters.google_calendar import GoogleCalendarAdapter
from app.domain.schemas import CalendarEventRequest
from app.services.token_store import TokenStore
from app.tools.base import Tool


class CreateCalendarEventTool(Tool):
    name = "create_calendar_event"

    def __init__(self, token_store: TokenStore, calendar_id: str) -> None:
        self._token_store = token_store
        self._calendar_id = calendar_id

    def execute(self, payload: Dict[str, Any], context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        if not context:
            raise HTTPException(status_code=401, detail="Missing authenticated context")
        session_id = context.get("session_id")
        db = context.get("db")
        if not session_id or not isinstance(db, Session):
            raise HTTPException(status_code=401, detail="Missing authenticated session")

        refresh_token = self._token_store.get_refresh_token(db, session_id)
        if not refresh_token:
            raise HTTPException(status_code=403, detail="Google Calendar is not connected for this session")

        adapter = GoogleCalendarAdapter(refresh_token=refresh_token, calendar_id=self._calendar_id)
        request = CalendarEventRequest(**payload)
        result = adapter.create_event(request)
        return result.model_dump()
