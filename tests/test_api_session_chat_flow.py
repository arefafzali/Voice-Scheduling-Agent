from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import build_router
from app.domain.schemas import AgentTurnResponse, ConversationStage, SessionState
from app.domain.session_store import InMemorySessionStore


class StubConversationService:
    def opening_prompt(self) -> str:
        return "Hi! I can schedule a meeting for you. What is your name?"

    def process_turn(self, state: SessionState, user_message: str) -> AgentTurnResponse:
        if state.stage == ConversationStage.COLLECT_NAME and user_message.strip():
            state.name = user_message.strip()
            state.stage = ConversationStage.COLLECT_DATE
            return AgentTurnResponse(
                assistant_message=f"Great to meet you, {state.name}. What date should I schedule the meeting for?",
                state=state,
            )

        return AgentTurnResponse(
            assistant_message="Please provide your name.",
            state=state,
        )


class StubToolAdapter:
    def invoke(self, request):
        return None


class StubOAuthService:
    def build_authorization_url(self, session_id: str, return_to: str = "/") -> str:
        return f"https://example.test/oauth?session_id={session_id}&return_to={return_to}"

    def handle_callback(self, db, state: str, code: str):
        return "stub-session", "/voice"

    def disconnect(self, db, session_id: str) -> bool:
        return True


class StubRealtimeService:
    webrtc_url = "https://api.openai.com/v1/realtime"

    def create_ephemeral_session(self) -> dict:
        return {
            "id": "sess_test",
            "model": "gpt-4o-realtime-preview",
            "voice": "alloy",
            "client_secret": {"value": "ek_test", "expires_at": 9999999999},
        }


class StubAuditLogService:
    def write(self, db, *, action: str, status: str, request_id: str | None, session_id: str | None, details: dict | None = None) -> None:
        return None


class StubTokenStore:
    def get_refresh_token(self, db, session_id: str):
        return None



def _build_test_client() -> TestClient:
    app = FastAPI()
    app.include_router(
        build_router(
            store=InMemorySessionStore(),
            conversation=StubConversationService(),
            tool_adapter=StubToolAdapter(),
            oauth_service=StubOAuthService(),
            realtime_service=StubRealtimeService(),
            audit_log_service=StubAuditLogService(),
            token_store=StubTokenStore(),
            default_timezone="America/Montreal",
            default_duration=30,
        )
    )
    return TestClient(app)


def test_session_start_sets_session_and_csrf_cookies() -> None:
    client = _build_test_client()

    response = client.post("/api/session/start")

    assert response.status_code == 200
    body = response.json()
    assert "session_id" in body
    assert body["state"]["stage"] == ConversationStage.COLLECT_NAME.value

    cookies = response.cookies
    assert cookies.get("vsa_session")
    assert cookies.get("vsa_csrf")


def test_chat_turn_uses_existing_session_cookie() -> None:
    client = _build_test_client()

    start = client.post("/api/session/start")
    csrf = start.cookies.get("vsa_csrf")

    response = client.post(
        "/api/chat",
        json={"user_message": "Aref"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["state"]["name"] == "Aref"
    assert body["state"]["stage"] == ConversationStage.COLLECT_DATE.value
