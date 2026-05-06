"""
Authentication router — HMAC-signed cookie session.

Tokens are stateless: derived from credentials + timestamp and verified
via HMAC signature. Survives server restarts and uvicorn --reload.
"""

import hashlib
import hmac
import time

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response

from src.config import Settings, setup_logger
from src.schema import LoginRequest

logger = setup_logger(Settings.LOG_DIR / "router.log", name="gitmanager.routers.auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Deterministic secret derived from credentials — stable across restarts.
_HMAC_KEY = hashlib.sha256(
    f"gitmanager:{Settings.GM_USERNAME}:{Settings.GM_PASSWORD}".encode()
).digest()

_MAX_AGE = 86400 * 7  # 7 days


def _sign_token(issued_at: int) -> str:
    """Create an HMAC-signed session token: 'timestamp.signature'."""
    payload = f"{Settings.GM_USERNAME}:{issued_at}"
    sig = hmac.new(_HMAC_KEY, payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{issued_at}.{sig}"


def _verify_token(token: str) -> bool:
    """Verify that a token is validly signed and not expired."""
    try:
        parts = token.split(".", 1)
        if len(parts) != 2:
            return False
        issued_at = int(parts[0])
        # Check expiry
        if time.time() - issued_at > _MAX_AGE:
            return False
        # Verify signature
        expected = _sign_token(issued_at)
        return hmac.compare_digest(token, expected)
    except (ValueError, TypeError):
        return False


def require_auth(gm_session: str | None = Cookie(default=None)) -> str:
    """FastAPI dependency — raises 401 if not authenticated."""
    if not gm_session or not _verify_token(gm_session):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return gm_session


@router.post("/login")
async def login(body: LoginRequest, response: Response):
    """Validate credentials and set signed session cookie."""
    if body.username == Settings.GM_USERNAME and body.password == Settings.GM_PASSWORD:
        token = _sign_token(int(time.time()))
        response.set_cookie(
            key="gm_session",
            value=token,
            httponly=True,
            samesite="lax",
            max_age=_MAX_AGE,
        )
        logger.info(f"Login successful for user: {body.username}")
        return {"status": "ok"}

    logger.warning(f"Failed login attempt for user: {body.username}")
    raise HTTPException(status_code=401, detail="Invalid credentials")


@router.post("/logout")
async def logout(response: Response, _: str = Depends(require_auth)):
    """Clear session cookie."""
    response.delete_cookie("gm_session")
    return {"status": "logged_out"}


@router.get("/check")
async def check(gm_session: str | None = Cookie(default=None)):
    """Check if current session is valid."""
    if gm_session and _verify_token(gm_session):
        return {"authenticated": True, "username": Settings.GM_USERNAME}
    return {"authenticated": False}
