"""
Upstream Service unit tests.

Covers:
- UpstreamService.pull: skipping disabled upstreams, handling missing paths, branch sync
- _get_sparse_subpaths: extracting relative targets from forward rules
- Blobless and sparse checkout optimizations
"""

import pytest
from src.core import UpstreamResolver
from src.schema.models import UpstreamEntry, ForwardRule
from src.services.upstream import UpstreamService


class TestUpstreamService:
    """Tests for pulling and cloning upstream repositories."""

    def test_skip_when_pull_disabled(self):
        upstreams = [
            UpstreamEntry(name="disabled-up", path="/tmp/.disabled-up", url="https://example.com", pull=False)
        ]
        results, updated = UpstreamService().pull(upstreams)
        assert results["disabled-up"] is True
        assert len(updated) == 0

    def test_missing_path_without_url_fails_gracefully(self):
        upstreams = [
            UpstreamEntry(name="no-url", path="/tmp/nonexistent-upstream-dir", url="", pull=True)
        ]
        results, updated = UpstreamService().pull(upstreams)
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

        subpaths = UpstreamResolver.resolve_sparse_subpaths(entry, forwards)
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
        subpaths = UpstreamResolver.resolve_sparse_subpaths(entry, forwards)
        assert subpaths == []

    def test_pull_upstreams_sparse_checkout_with_file_path(self, tmp_path):
        import subprocess
        origin_dir = tmp_path / "origin"
        origin_dir.mkdir()
        subprocess.run(["git", "init"], cwd=str(origin_dir), capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(origin_dir), capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(origin_dir), capture_output=True, check=True)

        (origin_dir / "skills").mkdir()
        (origin_dir / "skills" / "s.txt").write_text("s")
        (origin_dir / "helpers").mkdir()
        (origin_dir / "helpers" / "api.py").write_text("api")
        subprocess.run(["git", "add", "."], cwd=str(origin_dir), capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(origin_dir), capture_output=True, check=True)
        subprocess.run(["git", "branch", "-M", "master"], cwd=str(origin_dir), capture_output=True)

        target_dir = tmp_path / "target_upstream"
        entry = UpstreamEntry(
            name="test-sparse-file",
            path=str(target_dir),
            url=str(origin_dir),
            sparse=True,
            branch="master",
        )
        forwards = [
            ForwardRule(
                from_path=f"{target_dir}/helpers/api.py",
                to_path=str(tmp_path / "dst" / "api.py"),
                enabled=True,
            )
        ]

        results, updated = UpstreamService().pull([entry], forwards=forwards)
        assert results["test-sparse-file"] is True
        assert (target_dir / "helpers" / "api.py").exists()
