"""
Core Rate Limiter unit tests.

Covers:
- Scanner path detection patterns
- Whitelist resolution (localhost, private subnets, external IPs)
"""

import pytest
from src.core.rate_limiter import _is_scanner_path, _is_whitelisted


class TestRateLimiterHelpers:
    """Unit tests for rate limiter internal functions."""

    def test_scanner_path_detection(self):
        assert _is_scanner_path("/.env") is True
        assert _is_scanner_path("/api/.env.test") is True
        assert _is_scanner_path("/.git/config") is True
        assert _is_scanner_path("/.aws/credentials") is True
        assert _is_scanner_path("/backup/db.sql") is True
        assert _is_scanner_path("/key.pem") is True
        assert _is_scanner_path("/actuator/health") is True

    def test_normal_paths_not_detected(self):
        assert _is_scanner_path("/") is False
        assert _is_scanner_path("/api/projects") is False
        assert _is_scanner_path("/static/js/app.js") is False
        assert _is_scanner_path("/api/projects/test/run") is False

    def test_localhost_whitelisted(self):
        assert _is_whitelisted("127.0.0.1") is True
        assert _is_whitelisted("::1") is True
        assert _is_whitelisted("localhost") is True

    def test_private_ips_whitelisted(self):
        assert _is_whitelisted("192.168.1.100") is True
        assert _is_whitelisted("10.0.0.1") is True

    def test_external_ips_not_whitelisted(self):
        assert _is_whitelisted("185.177.72.70") is False
        assert _is_whitelisted("8.8.8.8") is False
