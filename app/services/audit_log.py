from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.domain.models import AuditLog


class AuditLogService:
    def write(
        self,
        db: Session,
        *,
        action: str,
        status: str,
        request_id: str | None,
        session_id: str | None,
        details: dict[str, Any] | None = None,
    ) -> None:
        payload = self._sanitize(details or {})
        row = AuditLog(
            id=str(uuid4()),
            request_id=request_id,
            session_id=session_id,
            action=action,
            status=status,
            details_json=json.dumps(payload, default=str),
        )
        db.add(row)
        db.commit()

    def _sanitize(self, details: dict[str, Any]) -> dict[str, Any]:
        redacted_keys = {
            "refresh_token",
            "access_token",
            "authorization",
            "client_secret",
            "openai_api_key",
            "token",
            "code",
        }
        sanitized: dict[str, Any] = {}
        for key, value in details.items():
            lowered = key.lower()
            if lowered in redacted_keys or "token" in lowered or "secret" in lowered:
                sanitized[key] = "***"
                continue
            if isinstance(value, str) and len(value) > 400:
                sanitized[key] = f"{value[:400]}..."
            else:
                sanitized[key] = value
        return sanitized
