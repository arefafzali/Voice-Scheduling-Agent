from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.adapters.google_calendar import GoogleCalendarAdapter
from app.domain.schemas import CalendarEventRequest
from app.services.token_store import TokenStore
from app.tools.base import Tool


class CreateCalendarEventTool(Tool):
    name = "create_calendar_event"

    def __init__(self, token_store: TokenStore, calendar_id: str) -> None:
        self._token_store = token_store
        self._calendar_id = calendar_id

    def _parse_datetime(self, value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if not isinstance(value, str) or not value.strip():
            return None

        candidate = value.strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            return None

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

        timezone = str(payload.get("timezone") or settings.default_timezone)
        tz = ZoneInfo(timezone)

        start_dt = self._parse_datetime(payload.get("start_iso") or payload.get("start"))
        if start_dt is None:
            raise HTTPException(status_code=422, detail="start_iso is required and must be ISO 8601")

        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=tz)
        else:
            start_dt = start_dt.astimezone(tz)

        end_dt = self._parse_datetime(payload.get("end_iso") or payload.get("end"))
        if end_dt is None:
            duration = payload.get("duration_minutes")
            try:
                duration_minutes = int(duration) if duration is not None else settings.default_duration_minutes
            except (TypeError, ValueError):
                duration_minutes = settings.default_duration_minutes
            end_dt = start_dt + timedelta(minutes=duration_minutes)
        elif end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=tz)
        else:
            end_dt = end_dt.astimezone(tz)

        summary = str(payload.get("summary") or payload.get("title") or "").strip()
        if not summary:
            name = str(payload.get("name") or "").strip()
            summary = f"Meeting with {name}" if name else "Meeting"

        description = str(payload.get("description") or "").strip()
        if not description:
            description = "Scheduled by Voice Scheduling Agent"

        adapter = GoogleCalendarAdapter(refresh_token=refresh_token, calendar_id=self._calendar_id)
        request = CalendarEventRequest(
            summary=summary,
            start_iso=start_dt,
            end_iso=end_dt,
            timezone=timezone,
            description=description,
        )
        result = adapter.create_event(request)
        return result.model_dump()
