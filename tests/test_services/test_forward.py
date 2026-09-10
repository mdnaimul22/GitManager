"""
Forward Service unit and integration tests.

Covers:
- Incremental file copy optimizations (ForwardEngine.should_copy, ForwardEngine.incremental_copy)
- ForwardService.forward execution
- ForwardService.cleanup_orphans: disk deletion, git index un-tracking, and manual skills preservation
"""

import subprocess
import time
import pytest
from src.schema.models import ForwardRule, UpstreamEntry
from src.core.forwarder import ForwardEngine
from src.services.forward import ForwardService


class TestIncrementalCopy:
    """Incremental copy helper functions."""

    def test_copy_if_newer_copies_new_file(self, tmp_path):
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst.txt"
        src.write_text("hello")

        assert ForwardEngine.should_copy(str(src), str(dst)) is True
        import shutil
        shutil.copy2(str(src), str(dst))
        assert dst.read_text() == "hello"

    def test_copy_if_newer_skips_unchanged(self, tmp_path):
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst.txt"
        src.write_text("hello")
        dst.write_text("hello")

        # Make dst newer than src
        time.sleep(0.05)
        dst.write_text("hello")

        assert ForwardEngine.should_copy(str(src), str(dst)) is False

    def test_copy_if_newer_copies_when_src_newer(self, tmp_path):
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst.txt"
        dst.write_text("old")
        time.sleep(0.05)
        src.write_text("new")

        assert ForwardEngine.should_copy(str(src), str(dst)) is True
        ForwardEngine.incremental_copy(str(src), str(dst))
        assert dst.read_text() == "new"

    def test_incremental_copy_skips_unchanged(self, tmp_path):
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst.txt"
        src.write_text("same")
        dst.write_text("same")
        time.sleep(0.05)
        dst.write_text("same")

        result = ForwardEngine.incremental_copy(str(src), str(dst))
        assert result == str(dst)


class TestOrphanCleanup:
    """ForwardService.cleanup_orphans removes dead upstream skills from disk and git index."""

    def test_orphan_detected_when_rule_removed(self):
        previous = {"/dst/skill-a", "/dst/skill-b", "/dst/skill-c"}
        current = {"/dst/skill-a", "/dst/skill-c"}
        orphans = previous - current
        assert orphans == {"/dst/skill-b"}

    def test_cleanup_removes_from_disk(self, tmp_path):
        orphan_dir = tmp_path / "orphan-skill"
        orphan_dir.mkdir()
        (orphan_dir / "SKILL.md").write_text("test")

        previous = {str(orphan_dir)}
        current = set()

        removed = ForwardService().cleanup_orphans(previous, current)
        assert "orphan-skill" in removed
        assert not orphan_dir.exists()

    def test_cleanup_removes_from_git_index_when_repo_root_given(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=str(repo), capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(repo), capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), capture_output=True, check=True)

        skill = repo / "skills" / "ghost-skill"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("ghost")
        subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), capture_output=True, check=True)

        # Run cleanup with repo_root
        previous = {str(skill)}
        current = set()
        removed = ForwardService(repo_root=str(repo)).cleanup_orphans(previous, current)

        assert "ghost-skill" in removed
        assert not skill.exists()

        result = subprocess.run(
            ["git", "ls-files", "--", "skills/ghost-skill/"],
            cwd=str(repo), capture_output=True, text=True, check=True
        )
        assert result.stdout.strip() == "", "Orphan must be removed from git index"

    def test_manual_skills_never_deleted(self, tmp_path):
        """User's own manual skills must NEVER be touched by orphan cleanup."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        # Managed skill
        managed = skills_dir / "managed-skill"
        managed.mkdir()
        (managed / "SKILL.md").write_text("managed")

        # Manual skill (never in registry)
        manual = skills_dir / "my-custom-helpers"
        manual.mkdir()
        (manual / "utils.py").write_text("# user code")

        current = {str(managed)}
        previous = {str(managed)}

        removed = ForwardService().cleanup_orphans(previous, current)
        assert len(removed) == 0
        assert manual.exists(), "User manual skill must survive"
        assert managed.exists()


class TestUpstreamSourceVerification:
    """Tests for dynamic sparse-checkout expansion and missing upstream source detection."""

    def test_dynamic_checkout_and_forward_when_source_in_upstream_git(self, tmp_path):
        # 1. Set up origin repo with skills/ and helpers/api.py
        origin_dir = tmp_path / "origin"
        origin_dir.mkdir()
        subprocess.run(["git", "init"], cwd=str(origin_dir), capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(origin_dir), capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(origin_dir), capture_output=True, check=True)

        (origin_dir / "skills").mkdir()
        (origin_dir / "skills" / "SKILL.md").write_text("my skill")
        (origin_dir / "helpers").mkdir()
        (origin_dir / "helpers" / "api.py").write_text("print('api')")
        subprocess.run(["git", "add", "."], cwd=str(origin_dir), capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(origin_dir), capture_output=True, check=True)

        # 2. Clone sparse clone that initially only checks out 'skills'
        clone_dir = tmp_path / "repo" / ".data" / ".upstream"
        clone_dir.parent.mkdir(parents=True)
        subprocess.run(["git", "clone", "--no-checkout", str(origin_dir), str(clone_dir)], capture_output=True, check=True)
        subprocess.run(["git", "sparse-checkout", "init", "--cone"], cwd=str(clone_dir), capture_output=True, check=True)
        subprocess.run(["git", "sparse-checkout", "set", "skills"], cwd=str(clone_dir), capture_output=True, check=True)
        # Checkout branch (master or main)
        res_co = subprocess.run(["git", "checkout", "master"], cwd=str(clone_dir), capture_output=True)
        if res_co.returncode != 0:
            subprocess.run(["git", "checkout", "main"], cwd=str(clone_dir), capture_output=True, check=True)

        # Before forward: helpers/api.py does not exist on disk
        target_src = str(clone_dir / "helpers" / "api.py")
        assert not (clone_dir / "helpers").exists()

        # 3. Define upstream entry and forward rule targeting helpers/api.py
        upstream = UpstreamEntry(
            name="test-upstream",
            upstream_id="up123456",
            path=str(clone_dir),
            url=str(origin_dir),
            sparse=True,
            branch="master",
        )
        dst_dir = tmp_path / "repo" / "destination"
        dst_dir.mkdir(parents=True)
        target_dst = str(dst_dir / "api.py")

        rule = ForwardRule(
            from_path=target_src,
            to_path=target_dst,
            upstream_id="up123456",
            enabled=True,
        )

        svc = ForwardService(repo_root=str(tmp_path / "repo"))
        copied, memory = svc.forward([rule], upstreams=[upstream])

        # 4. Verify helpers/api.py was dynamically checked out and forwarded
        assert "api.py" in copied
        assert (dst_dir / "api.py").exists()
        assert (dst_dir / "api.py").read_text() == "print('api')"
        assert len(memory) == 1

    def test_warns_when_upstream_file_genuinely_missing(self, tmp_path, caplog):
        import logging
        origin_dir = tmp_path / "origin"
        origin_dir.mkdir()
        subprocess.run(["git", "init"], cwd=str(origin_dir), capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(origin_dir), capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(origin_dir), capture_output=True, check=True)
        (origin_dir / "skills").mkdir()
        (origin_dir / "skills" / "SKILL.md").write_text("my skill")
        subprocess.run(["git", "add", "."], cwd=str(origin_dir), capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(origin_dir), capture_output=True, check=True)

        clone_dir = tmp_path / "repo" / ".data" / ".upstream"
        clone_dir.parent.mkdir(parents=True)
        subprocess.run(["git", "clone", str(origin_dir), str(clone_dir)], capture_output=True, check=True)

        target_src = str(clone_dir / "helpers" / "missing.py")
        upstream = UpstreamEntry(
            name="test-upstream",
            upstream_id="up123456",
            path=str(clone_dir),
            url=str(origin_dir),
            sparse=True,
            branch="master",
        )
        rule = ForwardRule(
            from_path=target_src,
            to_path=str(tmp_path / "dst" / "missing.py"),
            upstream_id="up123456",
            enabled=True,
        )

        fwd_logger = logging.getLogger("gitmanager.services.forward")
        fwd_logger.addHandler(caplog.handler)
        try:
            with caplog.at_level(logging.WARNING):
                svc = ForwardService(repo_root=str(tmp_path / "repo"))
                copied, memory = svc.forward([rule], upstreams=[upstream])
        finally:
            fwd_logger.removeHandler(caplog.handler)

        assert len(copied) == 0
        assert "UpStreaming Source file missing" in caplog.text

    def test_warns_when_non_upstream_source_missing(self, tmp_path, caplog):
        import logging
        rule = ForwardRule(
            from_path=str(tmp_path / "nonexistent" / "custom.py"),
            to_path=str(tmp_path / "dst" / "custom.py"),
            enabled=True,
        )
        fwd_logger = logging.getLogger("gitmanager.services.forward")
        fwd_logger.addHandler(caplog.handler)
        try:
            with caplog.at_level(logging.WARNING):
                svc = ForwardService(repo_root=str(tmp_path))
                copied, memory = svc.forward([rule])
        finally:
            fwd_logger.removeHandler(caplog.handler)

        assert len(copied) == 0
        assert "Source missing — skipping" in caplog.text
