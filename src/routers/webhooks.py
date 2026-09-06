"""
Webhook endpoints for instant sync.

Allows GitHub, GitLab, or external automation services to trigger
an immediate sync run for a project on push events.
"""

import hmac
import hashlib
from fastapi import APIRouter, Request, HTTPException, status

from src.schema import ProjectDetail
from src.services import get_project
from src.core import WorkerPool

router = APIRouter(
    prefix="/api/webhooks",
    tags=["webhooks"],
)

_pool: WorkerPool | None = None


def set_pool(pool: WorkerPool) -> None:
    """Inject shared WorkerPool."""
    global _pool
    _pool = pool


def _get_pool() -> WorkerPool:
    if _pool is None:
        raise HTTPException(status_code=503, detail="Worker pool not initialized")
    return _pool


@router.post("/{project_id}", status_code=status.HTTP_202_ACCEPTED)
async def api_trigger_webhook(project_id: str, request: Request):
    """
    Handle incoming webhook event (e.g. GitHub push event) to trigger instant sync.
    """
    project: ProjectDetail | None = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not project.webhook.enabled:
        raise HTTPException(status_code=403, detail="Webhooks are disabled for this project")

    # If a secret is configured, verify HMAC signature or token
    if project.webhook.secret:
        body = await request.body()
        secret_bytes = project.webhook.secret.encode("utf-8")

        gh_sig = request.headers.get("x-hub-signature-256")
        token_hdr = request.headers.get("x-webhook-token")
        token_param = request.query_params.get("token")

        verified = False
        if gh_sig:
            expected_sig = "sha256=" + hmac.new(secret_bytes, body, hashlib.sha256).hexdigest()
            if hmac.compare_digest(gh_sig, expected_sig):
                verified = True

        if not verified and token_hdr:
            if hmac.compare_digest(token_hdr, project.webhook.secret):
                verified = True

        if not verified and token_param:
            if hmac.compare_digest(token_param, project.webhook.secret):
                verified = True

        if not verified:
            raise HTTPException(status_code=401, detail="Invalid webhook signature or token")

    pool = _get_pool()
    triggered = pool.trigger_now(project_id)
    if not triggered:
        raise HTTPException(status_code=500, detail="Failed to trigger sync")

    return {
        "status": "triggered",
        "project_id": project_id,
        "detail": "Instant sync initiated",
    }
