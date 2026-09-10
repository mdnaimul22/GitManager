"""
Webhook API Integration Tests.

Covers:
- POST /api/webhooks/{project_id}
- Project validation (404 on nonexistent)
- Disabled webhook check (403 on disabled)
- HMAC SHA-256 signature verification (X-Hub-Signature-256)
- Secret token header & query parameter verification
- Triggering instant sync (202 Accepted)
"""

import hmac
import hashlib
import json
import pytest
from src.schema.models import ProjectUpdate, WebhookConfig


class TestWebhooksAPI:
    """Integration tests for webhook instant sync endpoint."""

    @pytest.fixture(autouse=True)
    def mock_trigger(self, monkeypatch):
        from src.services import WorkerPool
        monkeypatch.setattr(WorkerPool, "trigger_now", lambda self, pid: True)

    def test_webhook_nonexistent_project_returns_404(self, client):
        resp = client.post("/api/webhooks/nonexistent-project", json={"ref": "refs/heads/main"})
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Project not found"

    def test_webhook_disabled_returns_403(self, client, auth_client):
        # Ensure webhook is disabled for test-project
        auth_client.put("/api/projects/test-project", json={
            "webhook": {"enabled": False, "secret": ""},
        })

        resp = client.post("/api/webhooks/test-project", json={"ref": "refs/heads/main"})
        assert resp.status_code == 403
        assert "disabled" in resp.json()["detail"].lower()

    def test_webhook_enabled_without_secret_triggers_sync(self, client, auth_client):
        # Enable webhook without secret
        auth_client.put("/api/projects/test-project", json={
            "webhook": {"enabled": True, "secret": ""},
        })

        resp = client.post("/api/webhooks/test-project", json={"ref": "refs/heads/main"})
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "triggered"
        assert data["project_id"] == "test-project"

    def test_webhook_with_secret_valid_hmac_signature(self, client, auth_client):
        secret = "supersecretkey123"
        auth_client.put("/api/projects/test-project", json={
            "webhook": {"enabled": True, "secret": secret},
        })

        payload = json.dumps({"ref": "refs/heads/main", "commits": []}).encode("utf-8")
        signature = "sha256=" + hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()

        resp = client.post(
            "/api/webhooks/test-project",
            content=payload,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": signature,
            },
        )
        assert resp.status_code == 202
        assert resp.json()["status"] == "triggered"

    def test_webhook_with_secret_invalid_hmac_signature_fails(self, client, auth_client):
        secret = "supersecretkey123"
        auth_client.put("/api/projects/test-project", json={
            "webhook": {"enabled": True, "secret": secret},
        })

        payload = json.dumps({"ref": "refs/heads/main"}).encode("utf-8")
        wrong_sig = "sha256=0000000000000000000000000000000000000000000000000000000000000000"

        resp = client.post(
            "/api/webhooks/test-project",
            content=payload,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": wrong_sig,
            },
        )
        assert resp.status_code == 401
        assert "Invalid" in resp.json()["detail"]

    def test_webhook_with_token_header(self, client, auth_client):
        secret = "mytoken456"
        auth_client.put("/api/projects/test-project", json={
            "webhook": {"enabled": True, "secret": secret},
        })

        resp = client.post(
            "/api/webhooks/test-project",
            json={"ref": "refs/heads/main"},
            headers={"X-Webhook-Token": secret},
        )
        assert resp.status_code == 202
        assert resp.json()["status"] == "triggered"

    def test_webhook_with_token_query_param(self, client, auth_client):
        secret = "mytoken456"
        auth_client.put("/api/projects/test-project", json={
            "webhook": {"enabled": True, "secret": secret},
        })

        resp = client.post(
            f"/api/webhooks/test-project?token={secret}",
            json={"ref": "refs/heads/main"},
        )
        assert resp.status_code == 202
        assert resp.json()["status"] == "triggered"
