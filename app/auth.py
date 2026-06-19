"""Optional HTTP Basic authentication.

Auth is enabled whenever the ``ROBOCALL_PASSWORD`` environment variable is set.
When it is unset the app runs open — convenient for local development and the
test suite — and a loud warning is logged at startup so an unprotected public
deployment does not go unnoticed.

The username defaults to ``admin`` and can be overridden with
``ROBOCALL_USERNAME``. Environment variables are read on every request so the
behavior can be toggled (and tested) without re-importing the app.
"""

from __future__ import annotations

import logging
import os
import secrets

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

logger = logging.getLogger("robocall.auth")

# auto_error=False so we can send our own 401 with a WWW-Authenticate header,
# which is what makes browsers show the login prompt.
_security = HTTPBasic(auto_error=False)

# Paths that must stay reachable without credentials (e.g. platform health checks).
_PUBLIC_PATHS = {"/healthz"}

# Paths that run their own auth at the route level and so are skipped by the
# app-wide Basic-auth dependency (e.g. the upload endpoint, which also accepts
# an upload token to make the iOS Shortcut easy).
_SELF_AUTH_PATHS = {"/api/voicemails"}


def auth_enabled() -> bool:
    return bool(os.environ.get("ROBOCALL_PASSWORD"))


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Basic"},
    )


def _enforce_basic(
    request: Request, credentials: HTTPBasicCredentials | None
) -> None:
    """Require valid Basic credentials when a password is configured."""
    password = os.environ.get("ROBOCALL_PASSWORD")
    if not password:
        return  # Auth disabled.

    username = os.environ.get("ROBOCALL_USERNAME", "admin")
    if credentials is None:
        raise _unauthorized("Authentication required")

    # Constant-time comparison to avoid leaking length/content via timing.
    user_ok = secrets.compare_digest(credentials.username, username)
    pass_ok = secrets.compare_digest(credentials.password, password)
    if not (user_ok and pass_ok):
        raise _unauthorized("Invalid username or password")


def require_auth(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(_security),
) -> None:
    """App-wide dependency enforcing Basic auth when a password is configured."""
    if request.url.path in _PUBLIC_PATHS or request.url.path in _SELF_AUTH_PATHS:
        return
    _enforce_basic(request, credentials)


def require_upload_auth(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(_security),
) -> None:
    """Auth for the upload endpoint: accept a valid upload token OR Basic auth.

    Set ROBOCALL_UPLOAD_TOKEN to enable token auth (passed as ``?token=`` or an
    ``X-Upload-Token`` header), which keeps the iOS Shortcut configuration to a
    single URL. If no token is configured, this falls back to the same Basic
    auth as the rest of the app.
    """
    token = os.environ.get("ROBOCALL_UPLOAD_TOKEN")
    if token:
        supplied = request.query_params.get("token") or request.headers.get(
            "x-upload-token"
        )
        if supplied and secrets.compare_digest(supplied, token):
            return
    _enforce_basic(request, credentials)


def warn_if_unprotected() -> None:
    if not auth_enabled():
        logger.warning(
            "ROBOCALL_PASSWORD is not set - the app is running WITHOUT "
            "authentication. Anyone with the URL can read and add entries. "
            "Set ROBOCALL_PASSWORD (and optionally ROBOCALL_USERNAME) to "
            "require a login."
        )
