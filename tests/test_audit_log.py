from __future__ import annotations

import json

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.domain.models import AuditLog
from app.services.audit_log import AuditLogService


def test_audit_log_insertion_and_redaction() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    local_session = sessionmaker(bind=engine, future=True)

    service = AuditLogService()

    with local_session() as db:  # type: Session
        service.write(
            db,
            action="tool_execute",
            status="ok",
            request_id="req-1",
            session_id="sess-1",
            details={
                "tool_name": "create_calendar_event",
                "refresh_token": "very-secret-token",
                "note": "safe",
            },
        )

        row = db.execute(select(AuditLog)).scalar_one()
        assert row.action == "tool_execute"
        assert row.status == "ok"
        assert row.request_id == "req-1"
        payload = json.loads(row.details_json)
        assert payload["refresh_token"] == "***"
        assert payload["tool_name"] == "create_calendar_event"
