"""SHA-256 fingerprint of a PEM certificate, formatted to match
`openssl x509 -noout -fingerprint -sha256` (uppercase colon-separated hex over
the DER bytes). Dependency-free: parses the first CERTIFICATE block by hand."""
from __future__ import annotations

import base64
import hashlib
import re

_CERT_RE = re.compile(
    rb"-----BEGIN CERTIFICATE-----(.+?)-----END CERTIFICATE-----", re.DOTALL
)


def ca_fingerprint_sha256(pem_path: str) -> str | None:
    try:
        with open(pem_path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    m = _CERT_RE.search(data)
    if not m:
        return None
    try:
        der = base64.b64decode(b"".join(m.group(1).split()))
    except Exception:
        return None
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))
