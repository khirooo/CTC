from __future__ import annotations

import hashlib
import hmac
import re
import uuid

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _sign(secret: str, value: str) -> str:
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


class EmailMagicLink:
    def __init__(self, store, secret, app_origin, sender, ttl_seconds=900):
        self.store = store
        self.secret = secret
        self.app_origin = app_origin.rstrip("/")
        self.sender = sender
        self.ttl = ttl_seconds

    def start(self, email: str, now: int) -> str:
        email = (email or "").strip().lower()
        if not _EMAIL_RE.match(email):
            raise ValueError("invalid email")
        tid = uuid.uuid4().hex
        self.store.add_magic_link(tid, email, expires_at=now + self.ttl, created_at=now)
        token = f"{tid}.{_sign(self.secret, tid)}"
        link = f"{self.app_origin}/auth/magic?token={token}"
        self.sender.send_magic_link(email, link)
        return link

    def verify(self, token: str, now: int) -> str:
        tid, _, sig = (token or "").partition(".")
        if not tid or not hmac.compare_digest(_sign(self.secret, tid), sig):
            raise ValueError("link invalid or expired")
        row = self.store.get_magic_link(tid)
        if row is None or row["expires_at"] < now:
            raise ValueError("link invalid or expired")
        if not self.store.consume_magic_link(tid, now):
            raise ValueError("link invalid or expired")
        return row["email"]
