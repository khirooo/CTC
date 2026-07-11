from __future__ import annotations

import hashlib
import secrets
import uuid

from .crypto import decrypt, encrypt, fingerprint
from .identity import ConsumerIdentity
from ..store.auth_store import AuthStore


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def mint_proxy_token() -> str:
    return "github_pat_" + secrets.token_urlsafe(60)


class AuthRegistry:
    def __init__(self, store: AuthStore, key: bytes):
        self.store = store
        self.key = key

    # --- IdentityProvider ---
    def resolve(self, proxy_token: str) -> ConsumerIdentity | None:
        row = self.store.get_active_proxy_token(hash_token(proxy_token))
        if row is None:
            return None
        user = self.store.get_user_by_id(row["user_id"])
        if user is None:
            return None
        return ConsumerIdentity(user_id=user["id"], is_giver=(user["role"] == "giver"))

    # --- PatRegistry ---
    def pat_for(self, giver_id: str) -> str | None:
        row = self.store.get_giver_pat(giver_id)
        if row is None:
            return None
        return decrypt(row["ciphertext"], row["nonce"], self.key)

    def list_givers(self) -> list[str]:
        return self.store.list_giver_ids()

    def pat_health_status(self, giver_id: str) -> str | None:
        row = self.store.get_pat_health(giver_id)
        return row["status"] if row else None

    # --- issuance / onboarding ---
    def issue_proxy_token(self, user_id: str, now: int) -> tuple[str, str, str]:
        token = mint_proxy_token()
        tid = uuid.uuid4().hex
        fp = token[-4:]
        self.store.add_proxy_token(tid, hash_token(token), user_id, fp, now)
        return tid, token, fp

    def store_pat(self, user_id: str, pat: str, now: int) -> None:
        ct, nonce = encrypt(pat, self.key)
        self.store.set_giver_pat(user_id, ct, nonce, fingerprint(pat), now)

    def delete_pat(self, user_id: str) -> None:
        self.store.delete_giver_pat(user_id)
