from __future__ import annotations

import json
import logging
from collections import deque
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any


REQUEST_ID_CTX_KEY = "request_id"
_request_id_ctx: ContextVar[str | None] = ContextVar(REQUEST_ID_CTX_KEY, default=None)
_app_mode: str = "unknown"
_log_buffer: deque[dict[str, Any]] = deque(maxlen=300)
_SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "set-cookie",
    "refresh_token",
    "access_token",
    "client_secret",
    "openai_api_key",
    "token",
    "secret",
    "password",
    "code",
}


def set_request_id(request_id: str | None):
    return _request_id_ctx.set(request_id)


def reset_request_id(token) -> None:
    _request_id_ctx.reset(token)


def get_request_id() -> str | None:
    return _request_id_ctx.get()


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            lowered = key.lower()
            if lowered in _SENSITIVE_KEYS or "token" in lowered or "secret" in lowered:
                sanitized[key] = "***"
            else:
                sanitized[key] = _sanitize(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        if len(value) > 600:
            return f"{value[:600]}..."
        return value
    return value


def set_app_mode(app_mode: str) -> None:
    global _app_mode
    _app_mode = app_mode


def get_recent_logs(limit: int = 100) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    return list(_log_buffer)[-limit:]


class JsonFormatter(logging.Formatter):
    _reserved_record_fields = {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
    }

    def format(self, record: logging.LogRecord) -> str:
        request_id = _request_id_ctx.get()
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "app_mode": _app_mode,
        }
        if request_id:
            payload["request_id"] = request_id

        for key, value in record.__dict__.items():
            if key not in self._reserved_record_fields and not key.startswith("_"):
                payload[key] = _sanitize(value)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        _log_buffer.append(payload)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())
