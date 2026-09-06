"""
Core ConfigWatcher unit tests.

Covers:
- Loading configuration into Pydantic models
- Change detection with has_changed()
- Hot-reload diff reporting with reload()
"""

import json
import time
import pytest
from src.core.watcher import ConfigWatcher
from src.config import Settings, write_text, ensure_dir


class TestConfigWatcher:
    """Tests for ConfigWatcher hot-reloading and change detection."""

    @pytest.fixture()
    def watcher_env(self, tmp_path):
        """Create an isolated test project directory."""
        proj_dir = tmp_path / "watcher-test"
        proj_dir.mkdir()

        # Place inside Settings.RAW_DATA_DIR / watcher-test
        data_dir = f"{Settings.RAW_DATA_DIR}/watcher-test"
        ensure_dir(data_dir)

        write_text(f"{data_dir}/{Settings.UPSTREAM_FILE}", json.dumps({
            "upstreams": [
                {"name": "test-up", "path": "/tmp/.test-up", "url": "https://example.com/repo.git", "pull": True}
            ]
        }))
        write_text(f"{data_dir}/{Settings.FORWARD_FILE}", json.dumps({
            "forwards": [
                {"from": "/tmp/.test-up/skills/a", "to": "/tmp/watcher-test/skills/a", "enabled": True}
            ]
        }))
        write_text(f"{data_dir}/{Settings.AUTOMATION_FILE}", json.dumps({
            "schedule": {"interval_minutes": 10, "poll_interval_seconds": 30},
            "git": {"auto_push": False, "branch": "main", "commit_messages": {}},
        }))

        watcher = ConfigWatcher("watcher-test", str(proj_dir))
        return watcher, data_dir

    def test_initial_load(self, watcher_env):
        watcher, _ = watcher_env
        assert len(watcher.upstreams) == 1
        assert watcher.upstreams[0].name == "test-up"
        assert len(watcher.forwards) == 1
        assert watcher.automation.schedule.interval_minutes == 10
        assert watcher.has_changed() is False

    def test_has_changed_and_reload(self, watcher_env):
        watcher, data_dir = watcher_env
        assert watcher.has_changed() is False

        # Modify automation.json
        auto_rel = f"{data_dir}/{Settings.AUTOMATION_FILE}"
        time.sleep(0.05)
        write_text(auto_rel, json.dumps({
            "schedule": {"interval_minutes": 25, "poll_interval_seconds": 60},
            "git": {"auto_push": False, "branch": "main", "commit_messages": {}},
        }))

        assert watcher.has_changed() is True

        # Reload
        changes = watcher.reload()
        assert "schedule" in changes
        assert watcher.automation.schedule.interval_minutes == 25
        assert watcher.has_changed() is False
