"""
Authentication service — HMAC-signed session management and credential verification.

Tokens are stateless: derived from credentials + timestamp and verified
via HMAC signature. Survives server restarts and uvicorn --reload.
"""

import hashlib
import hmac
import time

from src.config import Settings, setup_logger

logger = setup_logger(Settings.LOG_DIR / "service.log", name="gitmanager.services.auth")

COOKIE_NAME = "gm_session"
MAX_AGE = 86400 * 7  # 7 days

# Deterministic secret derived from credentials — stable across restarts.
_HMAC_KEY = hashlib.sha256(
    f"gitmanager:{Settings.GM_USERNAME}:{Settings.GM_PASSWORD}".encode()
).digest()


class AuthService:
    """Service handling credential verification and stateless session tokens."""

    @staticmethod
    def verify_credentials(username: str, password: str) -> bool:
        """Validate credentials against configured admin credentials."""
        is_valid = (
            username == Settings.GM_USERNAME and
            password == Settings.GM_PASSWORD
        )
        if is_valid:
            logger.info(f"Credentials verified for user: {username}")
        else:
            logger.warning(f"Failed credential verification for user: {username}")
        return is_valid

    @staticmethod
    def sign_token(issued_at: int | None = None) -> str:
        """Create an HMAC-signed session token: 'timestamp.signature'."""
        ts = int(time.time()) if issued_at is None else issued_at
        payload = f"{Settings.GM_USERNAME}:{ts}"
        sig = hmac.new(_HMAC_KEY, payload.encode(), hashlib.sha256).hexdigest()[:32]
        return f"{ts}.{sig}"

    @staticmethod
    def verify_token(token: str) -> bool:
        """Verify that a session token is validly signed and not expired."""
        try:
            parts = token.split(".", 1)
            if len(parts) != 2:
                return False
            issued_at = int(parts[0])
            # Check expiry
            if time.time() - issued_at > MAX_AGE:
                return False
            # Verify signature
            expected = AuthService.sign_token(issued_at)
            return hmac.compare_digest(token, expected)
        except (ValueError, TypeError):
            return False
