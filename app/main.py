from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path

from fastapi import FastAPI
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.adapters.mcp_tool_adapter import MCPToolAdapter
from app.api.routes import build_router
from app.config import settings
from app.db import init_db
from app.domain.session_store import InMemorySessionStore
from app.services.conversation import ConversationService
from app.services.llm_agent import OpenAISchedulingAgent
from app.services.oauth import GoogleOAuthService, OAuthStateStore
from app.services.realtime import OpenAIRealtimeService
from app.services.audit_log import AuditLogService
from app.services.token_store import TokenStore
from app.tools.calendar_tool import CreateCalendarEventTool
from app.tools.registry import ToolRegistry
from app.utils.logging import configure_logging, reset_request_id, set_app_env, set_request_id

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    configure_logging(settings.log_level)
    set_app_env(settings.app_env)
    init_db()
    app = FastAPI(
        title=settings.app_name,
        docs_url="/swagger",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_logging_middleware(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request_id_token = set_request_id(request_id)
        started_at = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
            logger.exception(
                "request_failed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "latency_ms": latency_ms,
                },
            )
            reset_request_id(request_id_token)
            raise

        response.headers["x-request-id"] = request_id
        latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
        logger.info(
            "request_completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "latency_ms": latency_ms,
            },
        )
        reset_request_id(request_id_token)
        return response

    store = InMemorySessionStore()
    tools = ToolRegistry()
    token_store = TokenStore()
    audit_log_service = AuditLogService()

    tools.register(CreateCalendarEventTool(token_store=token_store, calendar_id=settings.google_calendar_id))

    tool_adapter = MCPToolAdapter(tools)
    oauth_service = GoogleOAuthService(token_store=token_store, state_store=OAuthStateStore())
    realtime_service = OpenAIRealtimeService(
        api_key=settings.openai_api_key,
        model=settings.openai_realtime_model,
        voice=settings.openai_realtime_voice,
        instructions=settings.openai_realtime_instructions,
        webrtc_url=settings.openai_realtime_webrtc_url,
    )
    llm_agent = OpenAISchedulingAgent(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
    )

    conversation = ConversationService(
        tools=tools,
        llm_agent=llm_agent,
        default_timezone=settings.default_timezone,
        default_duration=settings.default_duration_minutes,
    )

    app.include_router(
        build_router(
            store,
            conversation,
            tool_adapter=tool_adapter,
            oauth_service=oauth_service,
            realtime_service=realtime_service,
            audit_log_service=audit_log_service,
            token_store=token_store,
            default_timezone=settings.default_timezone,
            default_duration=settings.default_duration_minutes,
        )
    )

    client_dir = Path(__file__).parent.parent / "client"
    if client_dir.exists():
        app.mount("/client", StaticFiles(directory=client_dir, html=True), name="realtime-client")

    static_dir = Path(__file__).parent / "static"
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="ui")

    return app


app = create_app()
