"""
Authentication endpoint tests.

Covers: login, logout, session check, unauthorized access protection.
"""

import pytest
from src.config import Settings


class TestLogin:
    """POST /api/auth/login"""

    def test_login_valid_credentials(self, client):
        resp = client.post("/api/auth/login", json={
            "username": Settings.GM_USERNAME,
            "password": Settings.GM_PASSWORD,
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert "gm_session" in resp.cookies

    def test_login_wrong_password(self, client):
        resp = client.post("/api/auth/login", json={
            "username": Settings.GM_USERNAME,
            "password": "wrong_password",
        })
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid credentials"

    def test_login_wrong_username(self, client):
        resp = client.post("/api/auth/login", json={
            "username": "unknown_user",
            "password": Settings.GM_PASSWORD,
        })
        assert resp.status_code == 401

    def test_login_empty_body(self, client):
        resp = client.post("/api/auth/login", json={})
        assert resp.status_code == 422  # Validation error

    def test_login_missing_fields(self, client):
        resp = client.post("/api/auth/login", json={"username": "admin"})
        assert resp.status_code == 422


class TestSessionCheck:
    """GET /api/auth/check"""

    def test_check_unauthenticated(self, client):
        resp = client.get("/api/auth/check")
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False

    def test_check_after_login(self, auth_client):
        resp = auth_client.get("/api/auth/check")
        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is True
        assert data["username"] == Settings.GM_USERNAME


class TestLogout:
    """POST /api/auth/logout"""

    def test_logout_clears_session(self, auth_client):
        # Verify authenticated
        resp = auth_client.get("/api/auth/check")
        assert resp.json()["authenticated"] is True

        # Logout
        resp = auth_client.post("/api/auth/logout")
        assert resp.status_code == 200
        assert resp.json()["status"] == "logged_out"

        # Session should be invalid now
        resp = auth_client.get("/api/auth/check")
        assert resp.json()["authenticated"] is False

    def test_logout_without_session(self, client):
        resp = client.post("/api/auth/logout")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Not authenticated"


class TestProtectedRoutes:
    """Verify all /api/projects/* endpoints require authentication."""

    @pytest.mark.parametrize("method,path", [
        ("GET", "/api/projects"),
        ("POST", "/api/projects"),
        ("GET", "/api/projects/test-project"),
        ("PUT", "/api/projects/test-project"),
        ("DELETE", "/api/projects/test-project"),
        ("POST", "/api/projects/test-project/run"),
        ("POST", "/api/projects/test-project/stop"),
    ])
    def test_unauthenticated_returns_401(self, client, method, path):
        resp = client.request(method, path)
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Not authenticated"
