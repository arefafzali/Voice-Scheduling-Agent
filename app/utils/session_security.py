from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken


@dataclass
class SessionCookieCodec:
    secret_key: str

    def __post_init__(self) -> None:
        digest = hashlib.sha256(self.secret_key.encode("utf-8")).digest()
        key = base64.urlsafe_b64encode(digest)
        self._fernet = Fernet(key)

    def encode(self, session_id: str) -> str:
        payload = json.dumps({"sid": session_id}).encode("utf-8")
        return self._fernet.encrypt(payload).decode("utf-8")

    def decode(self, token: str | None) -> str | None:
        if not token:
            return None
        try:
            payload = self._fernet.decrypt(token.encode("utf-8"))
            data = json.loads(payload.decode("utf-8"))
            sid = data.get("sid")
            if isinstance(sid, str) and sid:
                return sid
            return None
        except (InvalidToken, ValueError, json.JSONDecodeError):
            return None
