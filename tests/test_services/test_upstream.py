"""
Upstream Service unit tests.

Covers:
- pull_upstreams: skipping disabled upstreams, handling missing paths, branch sync
"""

import pytest
from src.schema.models import UpstreamEntry
from src.services.upstream import pull_upstreams


class TestPullUpstreams:
    """Tests for pulling and cloning upstream repositories."""

    def test_skip_when_pull_disabled(self):
        upstreams = [
            UpstreamEntry(name="disabled-up", path="/tmp/.disabled-up", url="https://example.com", pull=False)
        ]
        results, updated = pull_upstreams(upstreams)
        assert results["disabled-up"] is True
        assert len(updated) == 0

    def test_missing_path_without_url_fails_gracefully(self):
        upstreams = [
            UpstreamEntry(name="no-url", path="/tmp/nonexistent-upstream-dir", url="", pull=True)
        ]
        results, updated = pull_upstreams(upstreams)
        assert results["no-url"] is False
