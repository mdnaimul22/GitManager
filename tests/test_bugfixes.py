"""
Tests for bug fixes applied in this session.

Covers:
- Bug #1: data/ not tracked by git (.gitignore)
- Bug #2: Hot-reload ordering (before sched.run_pending)
- Bug #3: PUT response includes live worker status
- Bug #5: Lock scope in update_project()
- Config API: get_mtime()
- Incremental copy: _copy_if_newer, _incremental_copy_function
- Rate limiter: whitelist, scanner detection, rate limiting
"""

import json
import os
import time
import tempfile
import threading

import pytest


# ══════════════════════════════════════════════════════════════════════════════
# Bug #1: data/ not tracked in git
# ══════════════════════════════════════════════════════════════════════════════

class TestGitignoreDataDir:
    """Verify data/ is in .gitignore and not git-tracked."""

    def test_data_in_gitignore(self):
        from src.config import read_text
        gitignore = read_text(".gitignore")
        assert "data/" in gitignore, "data/ must be in .gitignore"

    def test_data_not_tracked_by_git(self):
        import subprocess
        result = subprocess.run(
            ["git", "ls-files", "--", "data/"],
            capture_output=True, text=True, timeout=5,
            cwd=os.path.dirname(os.path.dirname(__file__)),
        )
        tracked_files = result.stdout.strip()
        assert tracked_files == "", f"data/ files still tracked: {tracked_files}"


# ══════════════════════════════════════════════════════════════════════════════
# Bug #2: Hot-reload ordering in pool.py
# ══════════════════════════════════════════════════════════════════════════════

class TestHotReloadOrdering:
    """Verify hot-reload check runs BEFORE sched.run_pending()."""

    def test_reload_before_sched_in_source(self):
        """Source code must have has_changed() before sched.run_pending()."""
        from src.config import read_text
        source = read_text("src/core/pool.py")

        reload_pos = source.find("has_changed()")
        sched_pos = source.find("sched.run_pending()")

        assert reload_pos > 0, "has_changed() not found in pool.py"
        assert sched_pos > 0, "sched.run_pending() not found in pool.py"
        assert reload_pos < sched_pos, (
            f"has_changed() (pos {reload_pos}) must come BEFORE "
            f"sched.run_pending() (pos {sched_pos})"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Bug #3: PUT response includes live status
# ══════════════════════════════════════════════════════════════════════════════

class TestPutResponseLiveStatus:
    """PUT /api/projects/{id} must reflect live worker status."""

    def test_update_while_running_shows_running(self, auth_client):
        """Start worker → update config → response must say 'running'."""
        # Start the worker
        auth_client.post("/api/projects/test-project/run")

        # Update something (schedule)
        resp = auth_client.put("/api/projects/test-project", json={
            "schedule": {"interval_minutes": 15, "poll_interval_seconds": 60},
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "running", (
            "PUT response must show 'running' when worker is active"
        )

        # Cleanup
        auth_client.post("/api/projects/test-project/stop")

    def test_update_while_idle_shows_idle(self, auth_client):
        """When no worker is running, PUT response must say 'idle'."""
        # Ensure stopped
        auth_client.post("/api/projects/test-project/stop")

        resp = auth_client.put("/api/projects/test-project", json={
            "schedule": {"interval_minutes": 10, "poll_interval_seconds": 60},
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "idle"


# ══════════════════════════════════════════════════════════════════════════════
# Bug #5: Lock scope — update_project returns consistent data
# ══════════════════════════════════════════════════════════════════════════════

class TestUpdateProjectAtomicity:
    """update_project() must return data consistent with what was written."""

    def test_update_forwards_returns_exact_count(self, auth_client):
        """After saving N forwards, response must have exactly N."""
        forwards = [
            {"from": f"/src/skill-{i}", "to": f"/dst/skill-{i}", "enabled": True}
            for i in range(5)
        ]
        resp = auth_client.put("/api/projects/test-project", json={
            "forwards": forwards,
        })
        assert resp.status_code == 200
        assert len(resp.json()["forwards"]) == 5

    def test_update_then_get_matches(self, auth_client):
        """GET after PUT must return the same data."""
        forwards = [
            {"from": "/x/a", "to": "/y/a", "enabled": True},
            {"from": "/x/b", "to": "/y/b", "enabled": False},
        ]
        put_resp = auth_client.put("/api/projects/test-project", json={
            "forwards": forwards,
        })
        get_resp = auth_client.get("/api/projects/test-project")

        assert put_resp.status_code == 200
        assert get_resp.status_code == 200
        assert len(put_resp.json()["forwards"]) == len(get_resp.json()["forwards"])


# ══════════════════════════════════════════════════════════════════════════════
# Config API: get_mtime()
# ══════════════════════════════════════════════════════════════════════════════

class TestGetMtime:
    """Verify get_mtime() works for both relative and absolute paths."""

    def test_mtime_returns_float(self):
        from src.config import get_mtime
        # Use a file we know exists
        mtime = get_mtime("main.py")
        assert isinstance(mtime, float)
        assert mtime > 0

    def test_mtime_absolute_path(self):
        from src.config import get_mtime
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"test")
            tmp = f.name
        try:
            mtime = get_mtime(tmp)
            assert isinstance(mtime, float)
            assert mtime > 0
        finally:
            os.unlink(tmp)

    def test_mtime_changes_after_write(self):
        from src.config import get_mtime
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"v1")
            tmp = f.name
        try:
            mtime1 = get_mtime(tmp)
            time.sleep(0.05)
            with open(tmp, "w") as f:
                f.write("v2")
            mtime2 = get_mtime(tmp)
            assert mtime2 >= mtime1, "mtime must increase after write"
        finally:
            os.unlink(tmp)


# ══════════════════════════════════════════════════════════════════════════════
# Incremental copy helpers
# ══════════════════════════════════════════════════════════════════════════════

class TestIncrementalCopy:
    """_copy_if_newer and _incremental_copy_function tests."""

    def test_copy_if_newer_copies_new_file(self, tmp_path):
        from src.services.forward import _copy_if_newer
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst.txt"
        src.write_text("hello")

        assert _copy_if_newer(str(src), str(dst)) is True
        assert dst.read_text() == "hello"

    def test_copy_if_newer_skips_unchanged(self, tmp_path):
        from src.services.forward import _copy_if_newer
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst.txt"
        src.write_text("hello")
        dst.write_text("hello")

        # Make dst newer than src
        time.sleep(0.05)
        dst.write_text("hello")

        assert _copy_if_newer(str(src), str(dst)) is False

    def test_copy_if_newer_copies_when_src_newer(self, tmp_path):
        from src.services.forward import _copy_if_newer
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst.txt"
        dst.write_text("old")
        time.sleep(0.05)
        src.write_text("new")

        assert _copy_if_newer(str(src), str(dst)) is True
        assert dst.read_text() == "new"

    def test_incremental_copy_function_skips_unchanged(self, tmp_path):
        from src.services.forward import _incremental_copy_function
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst.txt"
        src.write_text("same")
        dst.write_text("same")

        # Make dst newer
        time.sleep(0.05)
        dst.write_text("same")

        result = _incremental_copy_function(str(src), str(dst))
        assert result == str(dst), "Should return dst path when skipped"


# ══════════════════════════════════════════════════════════════════════════════
# Rate limiter middleware
# ══════════════════════════════════════════════════════════════════════════════

class TestRateLimiterHelpers:
    """Unit tests for rate limiter functions."""

    def test_scanner_path_detection(self):
        from src.core.rate_limiter import _is_scanner_path
        assert _is_scanner_path("/.env") is True
        assert _is_scanner_path("/api/.env.test") is True
        assert _is_scanner_path("/.git/config") is True
        assert _is_scanner_path("/.aws/credentials") is True
        assert _is_scanner_path("/backup/db.sql") is True
        assert _is_scanner_path("/key.pem") is True
        assert _is_scanner_path("/actuator/health") is True

    def test_normal_paths_not_detected(self):
        from src.core.rate_limiter import _is_scanner_path
        assert _is_scanner_path("/") is False
        assert _is_scanner_path("/api/projects") is False
        assert _is_scanner_path("/static/js/app.js") is False
        assert _is_scanner_path("/api/projects/test/run") is False

    def test_localhost_whitelisted(self):
        from src.core.rate_limiter import _is_whitelisted
        assert _is_whitelisted("127.0.0.1") is True
        assert _is_whitelisted("::1") is True
        assert _is_whitelisted("localhost") is True

    def test_private_ips_whitelisted(self):
        from src.core.rate_limiter import _is_whitelisted
        assert _is_whitelisted("192.168.1.100") is True
        assert _is_whitelisted("10.0.0.1") is True

    def test_external_ips_not_whitelisted(self):
        from src.core.rate_limiter import _is_whitelisted
        assert _is_whitelisted("185.177.72.70") is False
        assert _is_whitelisted("8.8.8.8") is False


class TestRateLimiterIntegration:
    """Integration tests for rate limiter with actual HTTP requests."""

    def test_scanner_path_returns_404_not_banned_for_localhost(self, auth_client):
        """Localhost hitting scanner paths should NOT be banned."""
        # These requests come from 127.0.0.1 (TestClient)
        resp1 = auth_client.get("/.env")
        resp2 = auth_client.get("/.git/config")
        # Should NOT be 403 (banned) — localhost is whitelisted
        assert resp1.status_code != 403, "Localhost must not be banned"
        assert resp2.status_code != 403, "Localhost must not be banned"

    def test_normal_endpoint_works(self, auth_client):
        """Normal API calls should work without rate limiting issues."""
        resp = auth_client.get("/api/projects")
        assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# Shared config loader (Bug #6)
# ══════════════════════════════════════════════════════════════════════════════

class TestSharedConfigLoader:
    """load_project_configs() returns consistent Pydantic models."""

    def test_load_returns_tuple_of_three(self):
        from src.services.project import load_project_configs
        upstreams, forwards, automation = load_project_configs(
            "test-project", "/tmp/test-project"
        )
        assert isinstance(upstreams, list)
        assert isinstance(forwards, list)

    def test_load_nonexistent_returns_empty(self):
        from src.services.project import load_project_configs
        upstreams, forwards, automation = load_project_configs(
            "nonexistent-xyz", "/tmp/nowhere"
        )
        assert upstreams == []
        assert forwards == []
