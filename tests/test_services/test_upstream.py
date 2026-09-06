"""
Upstream Service unit tests.

Covers:
- pull_upstreams: skipping disabled upstreams, handling missing paths, branch sync
- _get_sparse_subpaths: extracting relative targets from forward rules
- Blobless and sparse checkout optimizations
"""

import pytest
from src.schema.models import UpstreamEntry, ForwardRule
from src.services.upstream import pull_upstreams, _get_sparse_subpaths


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

    def test_get_sparse_subpaths_extraction(self):
        entry = UpstreamEntry(
            name="anthropic",
            path="/home/user/project/.data/.anthropics-skills",
            url="https://example.com/repo.git",
        )
        forwards = [
            ForwardRule(**{
                "from": "/home/user/project/.data/.anthropics-skills/skills/storage",
                "to": "/home/user/project/skills/storage",
                "enabled": True,
            }),
            ForwardRule(**{
                "from": "/home/user/project/.data/.anthropics-skills/docs",
                "to": "/home/user/project/docs",
                "enabled": True,
            }),
            ForwardRule(**{
                "from": "/home/user/project/.data/.other-repo/skills",
                "to": "/home/user/project/skills",
                "enabled": True,
            }),
            ForwardRule(**{
                "from": "/home/user/project/.data/.anthropics-skills/disabled",
                "to": "/home/user/project/disabled",
                "enabled": False,
            }),
        ]

        subpaths = _get_sparse_subpaths(entry, forwards)
        assert subpaths == ["docs", "skills/storage"]

    def test_get_sparse_subpaths_whole_repo_returns_empty(self):
        entry = UpstreamEntry(
            name="full-repo",
            path="/home/user/project/.data/.full-repo",
            url="https://example.com/repo.git",
        )
        forwards = [
            ForwardRule(**{
                "from": "/home/user/project/.data/.full-repo",
                "to": "/home/user/project/full-repo",
                "enabled": True,
            })
        ]
        subpaths = _get_sparse_subpaths(entry, forwards)
        assert subpaths == []
