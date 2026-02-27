from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from importlib import import_module

from sqlalchemy.orm import Session

from app.config import settings
from app.services.token_store import TokenStore


@dataclass
class OAuthStatePayload:
    session_id: str
    return_to: str
    expires_at: float


class OAuthStateStore:
    def __init__(self, signing_key: str | None = None) -> None:
        key = (signing_key or settings.session_secret_key).strip()
        if not key:
            raise ValueError("SESSION_SECRET_KEY is required to sign OAuth state")
        self._signing_key = key.encode("utf-8")

    def issue(self, session_id: str, return_to: str = "/", ttl_seconds: int = 600) -> str:
        payload = {
            "session_id": session_id,
            "return_to": return_to,
            "expires_at": time.time() + ttl_seconds,
        }
        payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        payload_b64 = self._b64_encode(payload_json)
        signature = hmac.new(self._signing_key, payload_b64.encode("utf-8"), hashlib.sha256).digest()
        signature_b64 = self._b64_encode(signature)
        return f"{payload_b64}.{signature_b64}"

    def consume(self, state: str) -> OAuthStatePayload | None:
        try:
            payload_b64, signature_b64 = state.split(".", 1)
        except ValueError:
            return None

        try:
            provided_signature = self._b64_decode(signature_b64)
        except Exception:
            return None

        expected_signature = hmac.new(
            self._signing_key,
            payload_b64.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(expected_signature, provided_signature):
            return None

        try:
            payload_raw = self._b64_decode(payload_b64)
            decoded = json.loads(payload_raw.decode("utf-8"))
            payload = OAuthStatePayload(
                session_id=str(decoded.get("session_id") or "").strip(),
                return_to=str(decoded.get("return_to") or "/").strip() or "/",
                expires_at=float(decoded.get("expires_at") or 0),
            )
        except (ValueError, TypeError, json.JSONDecodeError):
            return None

        if not payload.session_id:
            return None
        if payload.expires_at < time.time():
            return None
        return payload

    def _b64_encode(self, value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    def _b64_decode(self, value: str) -> bytes:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(f"{value}{padding}")


class GoogleOAuthService:
    def __init__(self, token_store: TokenStore, state_store: OAuthStateStore) -> None:
        self._token_store = token_store
        self._state_store = state_store

    def build_authorization_url(self, session_id: str, return_to: str = "/") -> str:
        flow = self._new_flow()
        state = self._state_store.issue(session_id, return_to=return_to)
        authorization_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
            state=state,
        )
        return authorization_url

    def handle_callback(self, db: Session, state: str, code: str) -> tuple[str, str]:
        payload = self._state_store.consume(state)
        if not payload:
            raise ValueError("Invalid or expired OAuth state")

        session_id = payload.session_id

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
        return session_id, payload.return_to

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
                    "auth_uri": settings.google_oauth_auth_uri,
                    "token_uri": settings.google_oauth_token_uri,
                }
            },
            scopes=settings.google_calendar_scopes,
            redirect_uri=settings.google_redirect_uri,
        )
