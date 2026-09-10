"""
Tests for Tunnel and Tailscale Service.
"""

from unittest.mock import patch

from src.schema import TunnelStatus
from src.services.tunnel import TunnelService


class TestTunnelService:
    """Test suite for tunnel inspection and toggle logic."""

    @patch("src.services.tunnel.is_tailscale_installed", return_value=False)
    def test_get_tunnel_status_not_installed(self, mock_installed):
        # Arrange & Act
        status = TunnelService(port=8000).get_status()

        # Assert
        assert isinstance(status, TunnelStatus)
        assert status.installed is False
        assert status.running is False
        assert status.funnel_active is False
        assert status.error == "Tailscale CLI is not installed"

    @patch("src.services.tunnel.is_tailscale_installed", return_value=True)
    @patch("src.services.tunnel.run_tailscale_json")
    def test_get_tunnel_status_daemon_down(self, mock_run_json, mock_installed):
        # Arrange
        mock_run_json.return_value = (False, None, "daemon not responding")

        # Act
        status = TunnelService(port=8000).get_status()

        # Assert
        assert status.installed is True
        assert status.running is False
        assert status.funnel_active is False
        assert "daemon" in (status.error or "")

    @patch("src.services.tunnel.is_tailscale_installed", return_value=True)
    @patch("src.services.tunnel.run_tailscale_json")
    def test_get_tunnel_status_funnel_active(self, mock_run_json, mock_installed):
        # Arrange
        status_payload = {
            "BackendState": "Running",
            "Self": {"DNSName": "my-node.ts.net."},
        }
        funnel_payload = {
            "AllowFunnel": {"my-node.ts.net:443": True},
            "Web": {"my-node.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8000"}}}},
        }

        def side_effect(args, **kwargs):
            if args == ["status"]:
                return True, status_payload, ""
            if args == ["funnel", "status"]:
                return True, funnel_payload, ""
            return False, None, "Unknown"

        mock_run_json.side_effect = side_effect

        # Act
        status = TunnelService(port=8000).get_status()

        # Assert
        assert status.installed is True
        assert status.running is True
        assert status.funnel_active is True
        assert status.domain == "my-node.ts.net"
        assert status.funnel_url == "https://my-node.ts.net"
        assert status.error is None

    @patch("src.services.tunnel.is_tailscale_installed", return_value=True)
    @patch("src.services.tunnel.run_tailscale_json")
    def test_get_tunnel_status_funnel_inactive(self, mock_run_json, mock_installed):
        # Arrange
        status_payload = {
            "BackendState": "Running",
            "Self": {"DNSName": "my-node.ts.net."},
        }
        funnel_payload = {}

        def side_effect(args, **kwargs):
            if args == ["status"]:
                return True, status_payload, ""
            if args == ["funnel", "status"]:
                return True, funnel_payload, ""
            return False, None, "Unknown"

        mock_run_json.side_effect = side_effect

        # Act
        status = TunnelService(port=8000).get_status()

        # Assert
        assert status.installed is True
        assert status.running is True
        assert status.funnel_active is False
        assert status.domain == "my-node.ts.net"
        assert status.funnel_url is None

    @patch("src.services.tunnel.run_tailscale_cmd")
    def test_toggle_funnel_enable(self, mock_cmd):
        # Arrange
        mock_cmd.return_value = (True, "Funnel started")

        # Act
        ok, msg = TunnelService(port=8000).toggle(enable=True)

        # Assert
        assert ok is True
        assert "Funnel started" in msg
        mock_cmd.assert_called_once_with(["funnel", "--bg", "8000"])

    @patch("src.services.tunnel.run_tailscale_cmd")
    def test_toggle_funnel_disable(self, mock_cmd):
        # Arrange
        mock_cmd.return_value = (True, "Funnel stopped")

        # Act
        ok, msg = TunnelService(port=8000).toggle(enable=False)

        # Assert
        assert ok is True
        assert "Funnel stopped" in msg
        mock_cmd.assert_called_once_with(["funnel", "--https=443", "off"])
