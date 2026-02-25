from __future__ import annotations

from typing import Any, Dict

from app.domain.schemas import CalendarEventRequest, CalendarEventResult
from app.integrations.google_calendar_integration import GoogleCalendarIntegration


class GoogleCalendarAdapter:
    def __init__(self, refresh_token: str, calendar_id: str) -> None:
        self._integration = GoogleCalendarIntegration(
            refresh_token=refresh_token,
            calendar_id=calendar_id,
        )

    def create_event(self, event: CalendarEventRequest) -> CalendarEventResult:
        payload: Dict[str, Any] = {
            "summary": event.summary,
            "description": event.description,
            "start": {"dateTime": event.start_iso.isoformat(), "timeZone": event.timezone},
            "end": {"dateTime": event.end_iso.isoformat(), "timeZone": event.timezone},
        }
        created = self._integration.create_event(payload)
        return CalendarEventResult(event_id=created["id"], html_link=created["htmlLink"])
