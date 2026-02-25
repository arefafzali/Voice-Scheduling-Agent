from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.services.token_store import TokenStore


def test_token_store_upsert_get_delete() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    local_session = sessionmaker(bind=engine, future=True)

    store = TokenStore()

    with local_session() as db:  # type: Session
        store.upsert_refresh_token(db, "s1", "rtok1")
        assert store.get_refresh_token(db, "s1") == "rtok1"

        store.upsert_refresh_token(db, "s1", "rtok2")
        assert store.get_refresh_token(db, "s1") == "rtok2"

        deleted = store.delete_refresh_token(db, "s1")
        assert deleted is True
        assert store.get_refresh_token(db, "s1") is None
