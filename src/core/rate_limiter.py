"""
Rate limiter & scanner detection middleware.

- General rate limit: max N requests per window per IP
- Scanner detection: auto-ban IPs probing sensitive paths (.env, .git, etc.)
- Banned IPs get 403 Forbidden instantly
"""

import time
import threading
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.config import Settings, setup_logger

logger = setup_logger(Settings.LOG_DIR / "security.log", name="gitmanager.core.rate_limiter")

# ── Scanner trap paths ────────────────────────────────────────────────────────
# Any request to these patterns = instant ban
SCANNER_PATTERNS: set[str] = {
    ".env", ".git", ".aws", ".ssh", ".docker",
    ".jenkins", ".svn", ".hg", ".bzr",
    "wp-admin", "wp-login", "wp-content", "wordpress",
    "phpmyadmin", "phpinfo", "adminer",
    "actuator", "debug", "console",
    "backup", "dump", "db.sql",
    "key.pem", "id_rsa", "credentials",
    "secret", ".htpasswd", ".htaccess",
    "web.config", "server-status",
}

# IPs that should never be rate-limited or banned
WHITELISTED_IPS: set[str] = {"127.0.0.1", "::1", "localhost", "testclient"}


def _is_whitelisted(ip: str) -> bool:
    """Check if IP is local/whitelisted."""
    return ip in WHITELISTED_IPS or ip.startswith("192.168.") or ip.startswith("10.")


def _is_scanner_path(path: str) -> bool:
    """Check if the request path matches known scanner patterns."""
    path_lower = path.lower()
    return any(pattern in path_lower for pattern in SCANNER_PATTERNS)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Per-IP rate limiter with scanner auto-ban.

    Args:
        app: ASGI application
        max_requests: Max requests per window (default: 60)
        window_seconds: Sliding window size (default: 60)
        ban_duration: How long banned IPs stay blocked in seconds (default: 3600)
        scanner_threshold: Number of scanner hits before ban (default: 2)
    """

    def __init__(
        self,
        app,
        max_requests: int = 60,
        window_seconds: int = 60,
        ban_duration: int = 3600,
        scanner_threshold: int = 2,
    ):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.ban_duration = ban_duration
        self.scanner_threshold = scanner_threshold

        # State — {ip: [timestamp, ...]}
        self._requests: dict[str, list[float]] = defaultdict(list)
        # Banned IPs — {ip: ban_expiry_timestamp}
        self._banned: dict[str, float] = {}
        # Scanner hit counts — {ip: count}
        self._scanner_hits: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def _get_client_ip(self, request: Request) -> str:
        """Extract real client IP from proxy headers."""
        # X-Real-IP (nginx default)
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
        # X-Forwarded-For (standard proxy header)
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _cleanup_old_entries(self, now: float) -> None:
        """Remove expired bans and old request timestamps."""
        # Cleanup expired bans
        expired = [ip for ip, expiry in self._banned.items() if now > expiry]
        for ip in expired:
            del self._banned[ip]
            self._scanner_hits.pop(ip, None)
            logger.info(f"🔓 Ban expired for {ip}")

        # Cleanup old request windows
        cutoff = now - self.window_seconds
        stale = []
        for ip, timestamps in self._requests.items():
            self._requests[ip] = [t for t in timestamps if t > cutoff]
            if not self._requests[ip]:
                stale.append(ip)
        for ip in stale:
            del self._requests[ip]

    def _ban_ip(self, ip: str, reason: str) -> None:
        """Ban an IP address."""
        self._banned[ip] = time.time() + self.ban_duration
        logger.warning(f"🚫 BANNED {ip} for {self.ban_duration}s — {reason}")

    async def dispatch(self, request: Request, call_next) -> Response:
        now = time.time()
        ip = self._get_client_ip(request)
        path = request.url.path

        # Skip rate limiting for whitelisted IPs (localhost, private network)
        if _is_whitelisted(ip):
            return await call_next(request)

        with self._lock:
            # Periodic cleanup (every ~100 requests)
            if sum(len(v) for v in self._requests.values()) % 100 == 0:
                self._cleanup_old_entries(now)

            # Check if IP is banned
            if ip in self._banned:
                if now < self._banned[ip]:
                    return Response(
                        content="Forbidden",
                        status_code=403,
                    )
                else:
                    del self._banned[ip]
                    self._scanner_hits.pop(ip, None)

            # Scanner detection — check BEFORE processing
            if _is_scanner_path(path):
                self._scanner_hits[ip] += 1
                hits = self._scanner_hits[ip]
                logger.warning(f"🔍 Scanner probe from {ip}: {path} (hit #{hits})")

                if hits >= self.scanner_threshold:
                    self._ban_ip(ip, f"scanner detected ({hits} probe hits)")
                    return Response(
                        content="Forbidden",
                        status_code=403,
                    )

            # General rate limit
            cutoff = now - self.window_seconds
            self._requests[ip] = [t for t in self._requests[ip] if t > cutoff]
            self._requests[ip].append(now)

            if len(self._requests[ip]) > self.max_requests:
                logger.warning(
                    f"⚡ Rate limit exceeded: {ip} "
                    f"({len(self._requests[ip])}/{self.max_requests} in {self.window_seconds}s)"
                )
                return Response(
                    content="Too Many Requests",
                    status_code=429,
                    headers={"Retry-After": str(self.window_seconds)},
                )

        return await call_next(request)
