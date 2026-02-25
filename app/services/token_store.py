from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.domain.models import OAuthToken


class TokenStore:
    def upsert_refresh_token(self, db: Session, session_id: str, refresh_token: str) -> None:
        existing = db.get(OAuthToken, session_id)
        if existing:
            existing.refresh_token = refresh_token
        else:
            db.add(OAuthToken(session_id=session_id, refresh_token=refresh_token))
        db.commit()

    def get_refresh_token(self, db: Session, session_id: str) -> str | None:
        stmt = select(OAuthToken.refresh_token).where(OAuthToken.session_id == session_id)
        return db.execute(stmt).scalar_one_or_none()

    def delete_refresh_token(self, db: Session, session_id: str) -> bool:
        stmt = delete(OAuthToken).where(OAuthToken.session_id == session_id)
        result = db.execute(stmt)
        db.commit()
        return bool(result.rowcount)
