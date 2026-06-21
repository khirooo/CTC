from __future__ import annotations

import hashlib
import hmac
import uuid

from ..store.auth_store import AuthStore


class SessionService:
    def __init__(self, store: AuthStore, secret: str, ttl_s: int = 86400):
        self.store = store
        self.secret = secret.encode()
        self.ttl_s = ttl_s

    def sign(self, value: str) -> str:
        return hmac.new(self.secret, value.encode(), hashlib.sha256).hexdigest()

    def verify(self, value: str, sig: str) -> bool:
        return hmac.compare_digest(self.sign(value), sig)

    def create(self, user_id: str, now: int) -> str:
        sid = uuid.uuid4().hex
        self.store.create_session(sid, user_id, now, self.ttl_s)
        return f"{sid}.{self.sign(sid)}"

    def _valid_sid(self, cookie_value: str) -> str | None:
        sid, _, sig = (cookie_value or "").partition(".")
        if not sid or not sig or not self.verify(sid, sig):
            return None
        return sid

    def user_id_for(self, cookie_value: str, now: int) -> str | None:
        sid = self._valid_sid(cookie_value)
        if sid is None:
            return None
        row = self.store.get_active_session(sid, now)
        return row["user_id"] if row else None

    def revoke(self, cookie_value: str) -> None:
        sid = self._valid_sid(cookie_value)
        if sid is not None:
            self.store.revoke_session(sid)
