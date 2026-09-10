"""
Webhook verification and instant sync orchestration service.
"""

import hashlib
import hmac

from src.config import Settings, setup_logger
from src.schema import ProjectDetail
from src.services.project import ProjectService
from src.services.pool import WorkerPool

logger = setup_logger(Settings.LOG_DIR / "service.log", name="gitmanager.services.webhook")


class WebhookService:
    """Service handling webhook signature verification and instant sync triggers."""

    def __init__(self, project_service: ProjectService | None = None) -> None:
        self.project_service = project_service or ProjectService()

    def get_project(self, project_id: str) -> ProjectDetail | None:
        """Fetch project configuration for webhook processing."""
        return self.project_service.get(project_id)

    @staticmethod
    def verify_request(
        secret: str,
        body: bytes,
        gh_sig: str | None = None,
        token_hdr: str | None = None,
        token_param: str | None = None,
    ) -> bool:
        """
        Verify incoming webhook event against configured project secret.
        Supports GitHub HMAC-SHA256 signature header, custom header, and query param token.
        """
        if not secret:
            return True

        secret_bytes = secret.encode("utf-8")

        # 1. GitHub HMAC-SHA256 signature
        if gh_sig:
            expected = "sha256=" + hmac.new(secret_bytes, body, hashlib.sha256).hexdigest()
            if hmac.compare_digest(gh_sig, expected):
                return True

        # 2. Custom header token
        if token_hdr and hmac.compare_digest(token_hdr, secret):
            return True

        # 3. Query param token
        if token_param and hmac.compare_digest(token_param, secret):
            return True

        logger.warning("Webhook authentication failed: signature or token mismatch")
        return False

    def trigger_sync(self, project_id: str, pool: WorkerPool) -> bool:
        """Trigger instant sync through the WorkerPool."""
        logger.info(f"Triggering instant sync for project '{project_id}' via webhook")
        return pool.trigger_now(project_id)
