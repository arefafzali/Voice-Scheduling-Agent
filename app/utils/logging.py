from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any


REQUEST_ID_CTX_KEY = "request_id"
_request_id_ctx: ContextVar[str | None] = ContextVar(REQUEST_ID_CTX_KEY, default=None)
_app_env: str = "unknown"


def set_request_id(request_id: str | None):
    return _request_id_ctx.set(request_id)


def reset_request_id(token) -> None:
    _request_id_ctx.reset(token)


def get_request_id() -> str | None:
    return _request_id_ctx.get()


def set_app_env(app_env: str) -> None:
    global _app_env
    _app_env = app_env


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
            "app_env": _app_env,
        }
        if request_id:
            payload["request_id"] = request_id

        for key, value in record.__dict__.items():
            if key not in self._reserved_record_fields and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())
