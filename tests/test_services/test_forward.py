"""
Forward Service unit and integration tests.

Covers:
- Incremental file copy optimizations (_copy_if_newer, _incremental_copy_function)
- forward_skills execution
- cleanup_orphans: disk deletion, git index un-tracking, and manual skills preservation
"""

import subprocess
import time
import pytest
from src.schema.models import ForwardRule
from src.services.forward import (
    _copy_if_newer,
    _incremental_copy_function,
    forward_skills,
    cleanup_orphans,
)


class TestIncrementalCopy:
    """Incremental copy helper functions."""

    def test_copy_if_newer_copies_new_file(self, tmp_path):
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst.txt"
        src.write_text("hello")

        assert _copy_if_newer(str(src), str(dst)) is True
        assert dst.read_text() == "hello"

    def test_copy_if_newer_skips_unchanged(self, tmp_path):
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst.txt"
        src.write_text("hello")
        dst.write_text("hello")

        # Make dst newer than src
        time.sleep(0.05)
        dst.write_text("hello")

        assert _copy_if_newer(str(src), str(dst)) is False

    def test_copy_if_newer_copies_when_src_newer(self, tmp_path):
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst.txt"
        dst.write_text("old")
        time.sleep(0.05)
        src.write_text("new")

        assert _copy_if_newer(str(src), str(dst)) is True
        assert dst.read_text() == "new"

    def test_incremental_copy_function_returns_dst(self, tmp_path):
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst.txt"
        src.write_text("same")
        dst.write_text("same")
        time.sleep(0.05)
        dst.write_text("same")

        result = _incremental_copy_function(str(src), str(dst))
        assert result == str(dst)


class TestOrphanCleanup:
    """cleanup_orphans removes dead upstream skills from disk and git index."""

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

        removed = cleanup_orphans(previous, current)
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
        removed = cleanup_orphans(previous, current, repo_root=str(repo))

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

        removed = cleanup_orphans(previous, current)
        assert len(removed) == 0
        assert manual.exists(), "User manual skill must survive"
        assert managed.exists()
