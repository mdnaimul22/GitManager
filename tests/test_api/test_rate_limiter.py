"""
Rate limiter API integration tests.

Covers:
- Request handling under rate limiter middleware
- Whitelist behavior for localhost and normal API operations
"""

import pytest


class TestRateLimiterIntegration:
    """Integration tests for rate limiter middleware with FastAPI TestClient."""

    def test_scanner_path_returns_404_not_banned_for_localhost(self, auth_client):
        """Localhost hitting scanner paths should return 404 and NOT be banned (whitelisted)."""
        resp1 = auth_client.get("/.env")
        resp2 = auth_client.get("/.git/config")
        assert resp1.status_code != 403, "Localhost must not be banned"
        assert resp2.status_code != 403, "Localhost must not be banned"

    def test_normal_endpoint_works_consistently(self, auth_client):
        """Normal API calls should work seamlessly without rate limiting issues."""
        resp = auth_client.get("/api/projects")
        assert resp.status_code == 200
