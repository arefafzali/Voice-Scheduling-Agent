from __future__ import annotations

import secrets
import time
from importlib import import_module
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import settings
from app.services.token_store import TokenStore

GOOGLE_CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


@dataclass
class OAuthStatePayload:
    session_id: str
    expires_at: float


class OAuthStateStore:
    def __init__(self) -> None:
        self._state_to_payload: dict[str, OAuthStatePayload] = {}

    def issue(self, session_id: str, ttl_seconds: int = 600) -> str:
        state = secrets.token_urlsafe(32)
        self._state_to_payload[state] = OAuthStatePayload(session_id=session_id, expires_at=time.time() + ttl_seconds)
        return state

    def consume(self, state: str) -> str | None:
        payload = self._state_to_payload.pop(state, None)
        if payload is None:
            return None
        if payload.expires_at < time.time():
            return None
        return payload.session_id


class GoogleOAuthService:
    def __init__(self, token_store: TokenStore, state_store: OAuthStateStore) -> None:
        self._token_store = token_store
        self._state_store = state_store

    def build_authorization_url(self, session_id: str) -> str:
        flow = self._new_flow()
        state = self._state_store.issue(session_id)
        authorization_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
            state=state,
        )
        return authorization_url

    def handle_callback(self, db: Session, state: str, code: str) -> str:
        session_id = self._state_store.consume(state)
        if not session_id:
            raise ValueError("Invalid or expired OAuth state")

        flow = self._new_flow()
        flow.fetch_token(code=code)

        credentials = flow.credentials
        refresh_token = credentials.refresh_token

        if not refresh_token:
            existing = self._token_store.get_refresh_token(db, session_id)
            if existing:
                refresh_token = existing

        if not refresh_token:
            raise ValueError("No refresh token returned by Google; revoke access and retry consent")

        self._token_store.upsert_refresh_token(db, session_id, refresh_token)
        return session_id

    def disconnect(self, db: Session, session_id: str) -> bool:
        return self._token_store.delete_refresh_token(db, session_id)

    def _new_flow(self):
        flow_module = import_module("google_auth_oauthlib.flow")
        flow_cls = getattr(flow_module, "Flow")
        return flow_cls.from_client_config(
            {
                "web": {
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            },
            scopes=GOOGLE_CALENDAR_SCOPES,
            redirect_uri=settings.google_redirect_uri,
        )
