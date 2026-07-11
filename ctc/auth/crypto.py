from __future__ import annotations

import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


MIN_SECRET_LEN = 16


def validate_secret(secret: str) -> None:
    """Reject a too-short CTC_SECRET_KEY at startup. The encryption key is derived
    by a bare sha256 (no salt/KDF — a deliberate, documented tradeoff), so a short
    or low-entropy secret is brute-forceable offline against an exfiltrated DB.
    Enforcing a minimum length is the cheap floor; raise ValueError if unmet."""
    if not secret or len(secret) < MIN_SECRET_LEN:
        raise ValueError(
            f"CTC_SECRET_KEY must be at least {MIN_SECRET_LEN} characters "
            f"(got {len(secret) if secret else 0})")


def derive_key(secret: str) -> bytes:
    return hashlib.sha256(secret.encode()).digest()  # 32 bytes -> AES-256


def encrypt(plaintext: str, key: bytes) -> tuple[bytes, bytes]:
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode(), None)
    return ct, nonce


def decrypt(ciphertext: bytes, nonce: bytes, key: bytes) -> str:
    return AESGCM(key).decrypt(nonce, ciphertext, None).decode()


def fingerprint(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()[:8]
