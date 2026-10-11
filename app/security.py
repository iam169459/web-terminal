"""Minimal HMAC-signed token auth.

No third-party JWT dependency: the token is ``base64(payload).hmac_sha256(payload)``.
The key is generated once and stored in the data directory, so tokens stay valid
across restarts but are useless on another host.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Optional

from . import config


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _sign(payload: str) -> str:
    return hmac.new(config.SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()


def issue_token(ttl: Optional[int] = None) -> str:
    payload = {"sub": config.USERNAME, "exp": int(time.time()) + (ttl or config.TOKEN_TTL)}
    encoded = _b64(json.dumps(payload, separators=(",", ":")).encode())
    return f"{encoded}.{_sign(encoded)}"


def verify_token(token: Optional[str]) -> bool:
    if not token or "." not in token:
        return False
    encoded, signature = token.rsplit(".", 1)
    if not hmac.compare_digest(signature, _sign(encoded)):
        return False
    try:
        payload = json.loads(_unb64(encoded))
    except (ValueError, TypeError):
        return False
    return bool(payload.get("exp", 0) > time.time())


def verify_password(password: str) -> bool:
    return hmac.compare_digest(password or "", config.PASSWORD)


def extract_token(authorization: Optional[str], query_token: Optional[str] = None) -> Optional[str]:
    """Accept ``Authorization: Bearer x`` or ``?token=x`` (used by websockets)."""
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return query_token
