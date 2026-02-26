from __future__ import annotations

import logging
import json
import secrets
from typing import Annotated
from collections.abc import Generator

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.adapters.google_calendar import GoogleCalendarAdapter
from app.adapters.mcp_tool_adapter import MCPToolAdapter
from app.config import settings
from app.domain.schemas import (
    AgentTurnResponse,
    CalendarEventRequest,
    CalendarEventResult,
    OAuthConnectionStatusResponse,
    OAuthCallbackResponse,
    OAuthStartResponse,
    RealtimeSessionResponse,
    RealtimeSessionConfigResponse,
    SessionState,
    StartSessionResponse,
    ToolExecutionRequest,
    ToolExecutionResponse,
    UserTurnRequest,
)
from app.db import SessionLocal
from app.domain.session_store import InMemorySessionStore
from app.services.conversation import ConversationService
from app.services.oauth import GoogleOAuthService
from app.services.realtime import OpenAIRealtimeService
from app.services.audit_log import AuditLogService
from app.services.token_store import TokenStore
from app.tools.context import (
    get_current_session_id,
    reset_current_db_session,
    set_current_db_session,
)
from app.utils.session_security import SessionCookieCodec
from app.utils.logging import get_recent_logs, get_request_id

logger = logging.getLogger(__name__)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def build_router(
    store: InMemorySessionStore,
    conversation: ConversationService,
    tool_adapter: MCPToolAdapter,
    oauth_service: GoogleOAuthService,
    realtime_service: OpenAIRealtimeService,
    audit_log_service: AuditLogService,
    token_store: TokenStore,
    default_timezone: str,
    default_duration: int,
) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["voice-scheduler"])
    session_codec = SessionCookieCodec(settings.session_secret_key)

    def _error_detail(user_message: str, *, action: str | None = None) -> dict[str, str]:
        detail = {"message": user_message}
        if action:
            detail["action"] = action
        return detail

    def _set_session_cookie(response: Response, session_id: str) -> None:
        encoded = session_codec.encode(session_id)
        response.set_cookie(
            key=settings.session_cookie_name,
            value=encoded,
            httponly=True,
            secure=settings.session_cookie_secure,
            samesite="lax",
            max_age=settings.session_cookie_max_age_seconds,
        )

    def _set_csrf_cookie(response: Response, csrf_token: str) -> None:
        response.set_cookie(
            key=settings.csrf_cookie_name,
            value=csrf_token,
            httponly=False,
            secure=settings.session_cookie_secure,
            samesite="lax",
            max_age=settings.session_cookie_max_age_seconds,
        )

    def _ensure_csrf_cookie(response: Response, csrf_cookie: str | None) -> str:
        token = csrf_cookie or secrets.token_urlsafe(32)
        _set_csrf_cookie(response, token)
        return token

    def _validate_csrf(csrf_cookie: str | None, csrf_header: str | None) -> None:
        if not csrf_cookie or not csrf_header or csrf_cookie != csrf_header:
            raise HTTPException(
                status_code=403,
                detail=_error_detail(
                    "CSRF validation failed.",
                    action="Retry with the CSRF cookie value in the X-CSRF-Token header.",
                ),
            )

    def _csrf_cookie(request: Request) -> str | None:
        return request.cookies.get(settings.csrf_cookie_name)

    def _csrf_header(request: Request) -> str | None:
        return request.headers.get(settings.csrf_header_name)

    def _resolve_session_id(
        request: Request,
        explicit_session_id: str | None,
    ) -> str | None:
        decoded_cookie_session = session_codec.decode(request.cookies.get(settings.session_cookie_name))
        return explicit_session_id or decoded_cookie_session or get_current_session_id()

    def _get_or_create_session(session_id: str | None) -> StartSessionResponse:
        if session_id:
            try:
                existing = store.get(session_id)
                return StartSessionResponse(
                    session_id=existing.session_id,
                    assistant_message="Session resumed.",
                    state=existing,
                )
            except KeyError:
                recovered = SessionState(
                    session_id=session_id,
                    timezone=default_timezone,
                    duration_minutes=default_duration,
                )
                store.save(recovered)
                return StartSessionResponse(
                    session_id=recovered.session_id,
                    assistant_message=conversation.opening_prompt(),
                    state=recovered,
                )

        state = store.create(timezone=default_timezone, duration_minutes=default_duration)
        opening = conversation.opening_prompt()
        store.save(state)
        logger.info("session_started", extra={"session_id": state.session_id})
        return StartSessionResponse(session_id=state.session_id, assistant_message=opening, state=state)

    def _write_audit(
        db: Session,
        *,
        action: str,
        status: str,
        session_id: str | None,
        details: dict | None = None,
    ) -> None:
        try:
            audit_log_service.write(
                db,
                action=action,
                status=status,
                request_id=get_request_id(),
                session_id=session_id,
                details=details,
            )
        except Exception:
            logger.exception("audit_log_write_failed", extra={"action": action, "status": status})

    def _is_admin_request(request: Request) -> bool:
        if not settings.admin_token:
            return False
        provided = request.headers.get("x-admin-token") or request.query_params.get("admin_token")
        return bool(provided and provided == settings.admin_token)

    def _require_feature_access(request: Request, *, enabled: bool, feature_name: str) -> None:
        if enabled:
            return
        if settings.is_prod and _is_admin_request(request):
            return
        raise HTTPException(
            status_code=403,
            detail=_error_detail(
                f"{feature_name} endpoint is disabled.",
                action="Use demo mode or provide a valid admin token in prod.",
            ),
        )

    @router.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @router.post("/session/start", response_model=StartSessionResponse)
    def start_session(
        request: Request,
        response: Response,
        session_id: Annotated[str | None, Query()] = None,
        force_new: Annotated[bool, Query(description="Set true to start a brand new session")]=False,
    ) -> StartSessionResponse:
        resolved = None if force_new else _resolve_session_id(request, session_id)
        payload = _get_or_create_session(resolved)
        _set_session_cookie(response, payload.session_id)
        _ensure_csrf_cookie(response, _csrf_cookie(request))
        return payload

    @router.get("/session/me", response_model=StartSessionResponse)
    def get_current_session(
        request: Request,
        response: Response,
        session_id: Annotated[str | None, Query()] = None,
    ) -> StartSessionResponse:
        resolved = _resolve_session_id(request, session_id)
        if not resolved:
            raise HTTPException(
                status_code=401,
                detail=_error_detail("No active session.", action="Call POST /api/session/start and retry."),
            )
        try:
            state = store.get(resolved)
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail=_error_detail("Session not found.", action="Start a new session with POST /api/session/start."),
            ) from exc

        payload = StartSessionResponse(
            session_id=state.session_id,
            assistant_message="Session resolved.",
            state=state,
        )
        _set_session_cookie(response, state.session_id)
        _ensure_csrf_cookie(response, _csrf_cookie(request))
        return payload

    @router.post("/chat", response_model=AgentTurnResponse, summary="Chat with scheduling agent")
    def chat_turn(
        request: Request,
        payload: UserTurnRequest,
        db: Annotated[Session, Depends(get_db)],
        response: Response,
    ) -> AgentTurnResponse:
        _validate_csrf(_csrf_cookie(request), _csrf_header(request))
        resolved_session_id = _resolve_session_id(request, None)
        if not resolved_session_id:
            raise HTTPException(
                status_code=401,
                detail=_error_detail("No active session.", action="Call POST /api/session/start and retry."),
            )

        try:
            state = store.get(resolved_session_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail=_error_detail("Session not found.", action="Start a new session with POST /api/session/start."),
            ) from exc

        db_token = set_current_db_session(db)
        try:
            turn_response = conversation.process_turn(state, payload.user_message)
        except HTTPException:
            _write_audit(
                db,
                action="chat_turn",
                status="error",
                session_id=resolved_session_id,
                details={"reason": "http_exception"},
            )
            raise
        except Exception as exc:
            logger.exception("conversation_turn_failed", extra={"session_id": resolved_session_id})
            _write_audit(
                db,
                action="chat_turn",
                status="error",
                session_id=resolved_session_id,
                details={"reason": "conversation_exception"},
            )
            raise HTTPException(
                status_code=500,
                detail=_error_detail(
                    "Conversation processing failed.",
                    action="Retry in a few seconds. If this persists, verify backend logs with request_id.",
                ),
            ) from exc
        finally:
            reset_current_db_session(db_token)

        store.save(turn_response.state)
        _write_audit(
            db,
            action="chat_turn",
            status="ok",
            session_id=resolved_session_id,
            details={"stage": turn_response.state.stage.value},
        )
        _set_session_cookie(response, resolved_session_id)
        _ensure_csrf_cookie(response, _csrf_cookie(request))
        return turn_response

    @router.post("/session/turn", response_model=AgentTurnResponse)
    def user_turn_current_session(
        payload: UserTurnRequest,
        db: Annotated[Session, Depends(get_db)],
        request: Request,
        response: Response,
        session_id: Annotated[str | None, Query()] = None,
    ) -> AgentTurnResponse:
        _validate_csrf(_csrf_cookie(request), _csrf_header(request))
        resolved_session_id = _resolve_session_id(request, session_id)
        if not resolved_session_id:
            raise HTTPException(
                status_code=401,
                detail=_error_detail("No active session.", action="Call POST /api/session/start and retry."),
            )

        try:
            state = store.get(resolved_session_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail=_error_detail("Session not found.", action="Start a new session with POST /api/session/start."),
            ) from exc

        db_token = set_current_db_session(db)
        try:
            turn_response = conversation.process_turn(state, payload.user_message)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("conversation_turn_failed", extra={"session_id": resolved_session_id})
            raise HTTPException(
                status_code=500,
                detail=_error_detail(
                    "Conversation processing failed.",
                    action="Retry in a few seconds. If this persists, verify backend logs with request_id.",
                ),
            ) from exc
        finally:
            reset_current_db_session(db_token)

        store.save(turn_response.state)
        _set_session_cookie(response, resolved_session_id)
        _ensure_csrf_cookie(response, _csrf_cookie(request))
        return turn_response

    @router.post("/session/{session_id}/turn", response_model=AgentTurnResponse, include_in_schema=False)
    def user_turn(session_id: str, request: UserTurnRequest, db: Annotated[Session, Depends(get_db)]) -> AgentTurnResponse:
        try:
            state = store.get(session_id)
        except KeyError as exc:
            logger.warning("session_not_found", extra={"session_id": session_id})
            raise HTTPException(
                status_code=404,
                detail=_error_detail("Session not found.", action="Start a new session with POST /api/session/start."),
            ) from exc

        db_token = set_current_db_session(db)
        try:
            response = conversation.process_turn(state, request.user_message)
        except Exception as exc:
            logger.exception("conversation_turn_failed", extra={"session_id": session_id})
            raise HTTPException(
                status_code=500,
                detail=_error_detail(
                    "Conversation processing failed.",
                    action="Retry in a few seconds. If this persists, verify backend logs with request_id.",
                ),
            ) from exc
        finally:
            reset_current_db_session(db_token)

        store.save(response.state)
        logger.info(
            "session_turn_processed",
            extra={"session_id": session_id, "stage": response.state.stage.value},
        )
        return response

    @router.get("/realtime/session-config", response_model=RealtimeSessionConfigResponse)
    def realtime_session_config() -> RealtimeSessionConfigResponse:
        return RealtimeSessionConfigResponse(
            transport="webrtc",
            sample_rate_hz=16000,
            input_audio_format="pcm16",
            output_audio_format="pcm16",
            default_timezone=default_timezone,
            default_duration_minutes=default_duration,
            confirmation_required=True,
        )

    @router.post("/realtime/session", response_model=RealtimeSessionResponse)
    def create_realtime_session(
        request: Request,
        response: Response,
        db: Annotated[Session, Depends(get_db)],
    ) -> RealtimeSessionResponse:
        _validate_csrf(_csrf_cookie(request), _csrf_header(request))
        session_payload = realtime_service.create_ephemeral_session()
        request_id = request.headers.get("x-request-id")
        if request_id:
            response.headers["x-request-id"] = request_id

        client_secret = session_payload.get("client_secret") if isinstance(session_payload, dict) else None
        if not isinstance(client_secret, dict) or not isinstance(client_secret.get("value"), str):
            logger.error("realtime_session_invalid_payload")
            raise HTTPException(
                status_code=502,
                detail=_error_detail(
                    "Realtime session response was invalid.",
                    action="Retry creating the realtime session.",
                ),
            )

        realtime_response = RealtimeSessionResponse(
            id=str(session_payload.get("id") or ""),
            model=str(session_payload.get("model") or settings.openai_realtime_model),
            voice=session_payload.get("voice"),
            webrtc_url=realtime_service.webrtc_url,
            client_secret={
                "value": client_secret["value"],
                "expires_at": client_secret.get("expires_at"),
            },
        )

        _write_audit(
            db,
            action="realtime_session_create",
            status="ok",
            session_id=_resolve_session_id(request, None),
            details={"model": str(session_payload.get("model") or settings.openai_realtime_model)},
        )
        return realtime_response

    @router.post("/tools/execute", response_model=ToolExecutionResponse)
    def execute_tool(
        request_context: Request,
        request: Annotated[dict, Body()],
        db: Annotated[Session, Depends(get_db)],
    ) -> ToolExecutionResponse:
        _validate_csrf(_csrf_cookie(request_context), _csrf_header(request_context))
        try:
            tool_name = request.get("tool_name") or request.get("tool")
            tool_payload = request.get("payload")
            if tool_payload is None:
                tool_payload = request.get("arguments")

            if isinstance(tool_payload, str):
                try:
                    tool_payload = json.loads(tool_payload)
                except ValueError as exc:
                    raise HTTPException(
                        status_code=422,
                        detail=_error_detail(
                            "Tool arguments must be valid JSON.",
                            action="Send arguments as a JSON object.",
                        ),
                    ) from exc

            if not isinstance(tool_name, str) or not isinstance(tool_payload, dict):
                raise HTTPException(
                    status_code=422,
                    detail=_error_detail(
                        "Invalid tool request shape.",
                        action="Provide {tool, arguments} or {tool_name, payload} with JSON object arguments.",
                    ),
                )

            normalized_request = ToolExecutionRequest(tool_name=tool_name, payload=tool_payload)
            effective_session = _resolve_session_id(request_context, None)
            if not effective_session:
                raise HTTPException(
                    status_code=401,
                    detail=_error_detail("No active session.", action="Call POST /api/session/start and retry."),
                )
            response = tool_adapter.invoke(normalized_request, context={"db": db, "session_id": effective_session})
            logger.info("tool_executed", extra={"tool_name": normalized_request.tool_name})
            _write_audit(
                db,
                action="tool_execute",
                status="ok",
                session_id=effective_session,
                details={"tool_name": normalized_request.tool_name},
            )
            return response
        except HTTPException:
            _write_audit(
                db,
                action="tool_execute",
                status="error",
                session_id=_resolve_session_id(request_context, None),
                details={"reason": "http_exception"},
            )
            raise
        except KeyError as exc:
            logger.warning("tool_not_found", extra={"tool_name": request.get("tool_name") or request.get("tool")})
            raise HTTPException(
                status_code=404,
                detail=_error_detail("Tool not found.", action="Check tool_name and retry."),
            ) from exc
        except Exception as exc:
            logger.exception("tool_execution_failed", extra={"tool_name": request.get("tool_name") or request.get("tool")})
            _write_audit(
                db,
                action="tool_execute",
                status="error",
                session_id=_resolve_session_id(request_context, None),
                details={"tool_name": request.get("tool_name") or request.get("tool")},
            )
            raise HTTPException(
                status_code=400,
                detail=_error_detail(
                    "Tool execution failed.",
                    action="Validate payload schema and ensure Google Calendar is connected for this session.",
                ),
            ) from exc

    @router.post("/debug/calendar/events", response_model=CalendarEventResult)
    def debug_create_calendar_event(
        request_context: Request,
        request: CalendarEventRequest,
        db: Annotated[Session, Depends(get_db)],
    ) -> CalendarEventResult:
        _require_feature_access(request_context, enabled=settings.enable_debug_endpoints, feature_name="Debug")
        _validate_csrf(_csrf_cookie(request_context), _csrf_header(request_context))
        resolved_session_id = _resolve_session_id(request_context, None)
        if not resolved_session_id:
            raise HTTPException(
                status_code=401,
                detail=_error_detail("No active session.", action="Call POST /api/session/start and retry."),
            )

        refresh_token = token_store.get_refresh_token(db, resolved_session_id)
        if not refresh_token:
            raise HTTPException(
                status_code=403,
                detail=_error_detail(
                    "Google Calendar is not connected for this session.",
                    action="Complete OAuth via GET /api/auth/google/start, then retry.",
                ),
            )
        calendar_adapter = GoogleCalendarAdapter(refresh_token=refresh_token, calendar_id=settings.google_calendar_id)
        try:
            created = calendar_adapter.create_event(request)
            logger.info("debug_calendar_event_created", extra={"event_id": created.event_id})
            return created
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("debug_calendar_event_failed")
            raise HTTPException(
                status_code=400,
                detail=_error_detail(
                    "Calendar event creation failed.",
                    action="Verify start/end datetime are timezone-aware and OAuth access is still valid.",
                ),
            ) from exc

    @router.get("/auth/google/start", response_model=OAuthStartResponse)
    def auth_google_start(
        request: Request,
        response: Response,
        session_id: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
        return_to: Annotated[str, Query(description="UI path to return to after OAuth callback")]= "/",
        redirect: Annotated[bool, Query(description="Set false to return authorization_url as JSON")]=True,
    ) -> OAuthStartResponse | RedirectResponse:
        resolved_session_id = _resolve_session_id(request, session_id)
        start_payload = _get_or_create_session(resolved_session_id)
        safe_return_to = return_to if return_to.startswith("/") else "/"
        try:
            authorization_url = oauth_service.build_authorization_url(
                session_id=start_payload.session_id,
                return_to=safe_return_to,
            )
        except Exception as exc:
            logger.exception("oauth_start_failed")
            raise HTTPException(
                status_code=503,
                detail=_error_detail(
                    "OAuth start failed.",
                    action="Verify GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_REDIRECT_URI, then retry.",
                ),
            ) from exc

        _set_session_cookie(response, start_payload.session_id)
        _ensure_csrf_cookie(response, _csrf_cookie(request))

        if redirect:
            redirect_response = RedirectResponse(url=authorization_url, status_code=302)
            _set_session_cookie(redirect_response, start_payload.session_id)
            _ensure_csrf_cookie(redirect_response, _csrf_cookie(request))
            return redirect_response

        return OAuthStartResponse(authorization_url=authorization_url)

    @router.get("/auth/google/callback")
    def auth_google_callback(
        state: Annotated[str, Query(min_length=1)],
        code: Annotated[str, Query(min_length=1)],
        db: Annotated[Session, Depends(get_db)],
    ) -> RedirectResponse:
        try:
            session_id, return_to = oauth_service.handle_callback(db=db, state=state, code=code)
            _write_audit(
                db,
                action="oauth_callback",
                status="ok",
                session_id=session_id,
                details={"provider": "google"},
            )
        except ValueError as exc:
            _write_audit(
                db,
                action="oauth_callback",
                status="error",
                session_id=None,
                details={"reason": "invalid_state_or_token"},
            )
            raise HTTPException(
                status_code=400,
                detail=_error_detail(
                    str(exc),
                    action="Restart OAuth from GET /api/auth/google/start and complete consent in one flow.",
                ),
            ) from exc
        except Exception as exc:
            logger.exception("oauth_callback_failed")
            _write_audit(
                db,
                action="oauth_callback",
                status="error",
                session_id=None,
                details={"reason": "callback_exception"},
            )
            raise HTTPException(
                status_code=500,
                detail=_error_detail(
                    "OAuth callback failed.",
                    action="Retry OAuth start and callback. If it persists, inspect backend logs with request_id.",
                ),
            ) from exc

        safe_return_to = return_to if return_to.startswith("/") else "/"
        redirect_response = RedirectResponse(
            url=f"{settings.app_base_url}{safe_return_to}?oauth=connected&session_id={session_id}",
            status_code=302,
        )
        _set_session_cookie(redirect_response, session_id)
        _set_csrf_cookie(redirect_response, secrets.token_urlsafe(32))
        return redirect_response

    @router.get("/logs")
    def get_logs(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=300)] = 100,
    ) -> dict[str, object]:
        _require_feature_access(request, enabled=settings.enable_logs_endpoint, feature_name="Logs")
        logs = get_recent_logs(limit=limit)
        return {"count": len(logs), "logs": logs}

    @router.get("/auth/google/status", response_model=OAuthConnectionStatusResponse)
    def auth_google_status(
        request: Request,
        db: Annotated[Session, Depends(get_db)],
        session_id: Annotated[str | None, Query()] = None,
    ) -> OAuthConnectionStatusResponse:
        resolved_session_id = _resolve_session_id(request, session_id)
        if not resolved_session_id:
            return OAuthConnectionStatusResponse(session_id=None, connected=False)

        refresh_token = token_store.get_refresh_token(db, resolved_session_id)
        return OAuthConnectionStatusResponse(session_id=resolved_session_id, connected=bool(refresh_token))

    @router.post("/auth/google/disconnect")
    def auth_google_disconnect(
        request: Request,
        db: Annotated[Session, Depends(get_db)],
        payload: Annotated[dict | None, Body()] = None,
    ) -> OAuthCallbackResponse:
        _validate_csrf(_csrf_cookie(request), _csrf_header(request))
        explicit_session_id = payload.get("session_id") if isinstance(payload, dict) else None
        resolved_session_id = _resolve_session_id(request, explicit_session_id)
        if not resolved_session_id:
            raise HTTPException(
                status_code=401,
                detail=_error_detail("No active session to disconnect.", action="Start or resume a session and retry."),
            )
        oauth_service.disconnect(db=db, session_id=resolved_session_id)
        _write_audit(
            db,
            action="oauth_disconnect",
            status="ok",
            session_id=resolved_session_id,
            details={"provider": "google"},
        )
        return OAuthCallbackResponse(session_id=resolved_session_id, status="disconnected")

    return router
