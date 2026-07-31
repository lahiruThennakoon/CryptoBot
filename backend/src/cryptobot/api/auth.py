"""Single-operator bearer-token auth.

The token is API_SECRET_KEY from the environment. Suitable for a localhost/
VPN-bound single-operator deployment (docs/threat-model.md T3); replace with
a session-based flow before any multi-user or public exposure.
"""

from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from cryptobot.config import get_settings

_bearer = HTTPBearer(auto_error=False)


async def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    expected = get_settings().api_secret_key.get_secret_value()
    if expected in ("", "dev-only-not-secret"):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "API_SECRET_KEY is not configured — refusing to serve (fail closed)",
        )
    if credentials is None or not secrets.compare_digest(credentials.credentials, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing token")
