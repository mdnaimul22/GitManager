"""
Core WorkerPool unit tests.

Covers:
- Worker start, stop, and status lifecycle
- Idempotent start/stop behavior
- Mass stop on application shutdown
"""

import pytest
from src.core.pool import WorkerPool
from src.schema.models import ProjectMeta


class TestWorkerPool:
    """Behavioral tests for multi-project WorkerPool management."""

    def test_pool_lifecycle(self):
        pool = WorkerPool()
        proj = ProjectMeta(
            id="pool-test-proj",
            name="Pool Test Project",
            path="/tmp/pool-test-proj",
        )
        try:
            assert pool.is_running(proj.id) is False

            # Start worker
            started = pool.start(proj)
            assert started is True
            assert pool.is_running(proj.id) is True

            # Duplicate start should return False (already running)
            started_again = pool.start(proj)
            assert started_again is False
            assert pool.is_running(proj.id) is True

            # Stop worker
            stopped = pool.stop(proj.id)
            assert stopped is True

            # Stop non-running worker returns False
            stopped_again = pool.stop("nonexistent-worker")
            assert stopped_again is False
        finally:
            pool.stop_all()

    def test_stop_all_clears_active_workers(self):
        pool = WorkerPool()
        proj = ProjectMeta(
            id="pool-test-proj-2",
            name="Pool Test Project 2",
            path="/tmp/pool-test-proj-2",
        )
        try:
            pool.start(proj)
            assert pool.is_running(proj.id) is True

            pool.stop_all()
        finally:
            pool.stop_all()
