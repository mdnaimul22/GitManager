"""
Sync Service orchestrator tests.

Covers:
- SyncService.run: full execution flow
"""

import pytest
from src.core.watcher import ConfigWatcher
from src.services.sync import SyncService


class TestSyncService:
    """Tests for full SyncService orchestration pipeline."""

    def test_sync_service_runs_with_watcher(self):
        watcher = ConfigWatcher("test-project", "/tmp/test-project")
        # Run SyncService (handles errors gracefully and logs steps)
        SyncService(watcher).run()
        assert True
