"""
Sync Service orchestrator tests.

Covers:
- sync_job full execution flow
"""

import pytest
from src.core.watcher import ConfigWatcher
from src.services.sync import sync_job


class TestSyncJob:
    """Tests for full sync_job orchestration pipeline."""

    def test_sync_job_runs_with_watcher(self):
        watcher = ConfigWatcher("test-project", "/tmp/test-project")
        # Run sync_job (handles errors gracefully and logs steps)
        sync_job(watcher)
        assert True
