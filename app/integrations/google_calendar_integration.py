from __future__ import annotations

from typing import Any, Dict

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

from app.config import settings

class GoogleCalendarIntegration:
    def __init__(self, refresh_token: str, calendar_id: str) -> None:
        if not refresh_token:
            raise ValueError("Refresh token is required for calendar integration")
        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=settings.google_oauth_token_uri,
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            scopes=settings.google_calendar_scopes,
        )
        credentials.refresh(Request())
        self._calendar_id = calendar_id
        self._client = build("calendar", "v3", credentials=credentials, cache_discovery=False)

    def create_event(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return (
            self._client.events()
            .insert(calendarId=self._calendar_id, body=payload)
            .execute()
        )
