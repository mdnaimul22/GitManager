"""
API tests for system tunnel router.
"""

from unittest.mock import patch

from src.schema import TunnelStatus


class TestSystemTunnelAPI:
    """Test suite for /api/system/tunnel endpoints."""

    def test_unauthenticated_access_denied(self, client):
        """Unauthenticated requests must return 401 Unauthorized."""
        resp_get = client.get("/api/system/tunnel")
        assert resp_get.status_code == 401

        resp_post = client.post("/api/system/tunnel/funnel", json={"enable": True})
        assert resp_post.status_code == 401

    @patch("src.routers.system.get_tunnel_status")
    def test_get_tunnel_status_endpoint(self, mock_get_status, auth_client):
        # Arrange
        mock_get_status.return_value = TunnelStatus(
            installed=True,
            running=True,
            funnel_active=True,
            domain="test.ts.net",
            funnel_url="https://test.ts.net",
            port=8000,
            error=None,
        )

        # Act
        resp = auth_client.get("/api/system/tunnel")

        # Assert
        assert resp.status_code == 200
        data = resp.json()
        assert data["installed"] is True
        assert data["funnel_active"] is True
        assert data["funnel_url"] == "https://test.ts.net"

    @patch("src.routers.system.toggle_funnel")
    @patch("src.routers.system.get_tunnel_status")
    def test_toggle_funnel_success(self, mock_get_status, mock_toggle, auth_client):
        # Arrange
        mock_toggle.return_value = (True, "Funnel updated")
        mock_get_status.return_value = TunnelStatus(
            installed=True,
            running=True,
            funnel_active=True,
            domain="test.ts.net",
            funnel_url="https://test.ts.net",
            port=8000,
        )

        # Act
        resp = auth_client.post("/api/system/tunnel/funnel", json={"enable": True})

        # Assert
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "Funnel updated" in data["message"]

    @patch("src.routers.system.toggle_funnel")
    def test_toggle_funnel_failure(self, mock_toggle, auth_client):
        # Arrange
        mock_toggle.return_value = (False, "Permission denied")

        # Act
        resp = auth_client.post("/api/system/tunnel/funnel", json={"enable": True})

        # Assert
        assert resp.status_code == 400
        data = resp.json()
        assert "Permission denied" in data["detail"]
