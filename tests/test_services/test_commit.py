"""
Commit Service unit and integration tests.

Covers:
- CommitService.classify: Separates upstream-origin files and manual user edits
- CommitService.commit_and_push: Per-upstream commit templating and manual commit templating
"""

import subprocess
import pytest
from src.schema.models import CommitMessages, ForwardRule, UpstreamEntry
from src.services.commit import CommitService


class TestCommitService:
    """Tests for classifying git status changes into upstream and manual buckets."""

    def test_separates_upstream_and_manual_changes(self):
        repo_root = "/home/user/project"
        upstreams = [
            UpstreamEntry(name="anthropic", path=".anthropics-skills", url="https://github.com/a/b.git")
        ]
        forwards = [
            ForwardRule(**{"from": ".anthropics-skills/skills", "to": "skills/storage/anthropic", "enabled": True})
        ]

        status_output = (
            " M skills/storage/anthropic/pdf/SKILL.md\n"
            "?? skills/storage/my_skills/custom-tool/SKILL.md\n"
            " M .agents/rules/coding-standards.md\n"
        )

        svc = CommitService(repo_root=repo_root)
        upstream_changes, manual_changes = svc.classify(status_output, forwards, upstreams)

        assert "anthropic" in upstream_changes
        assert upstream_changes["anthropic"] == ["skills/storage/anthropic/pdf/SKILL.md"]
        assert len(manual_changes) == 2
        assert "skills/storage/my_skills/custom-tool/SKILL.md" in manual_changes
        assert ".agents/rules/coding-standards.md" in manual_changes

    def test_disabled_forward_rule_treated_as_manual(self):
        repo_root = "/home/user/project"
        upstreams = [
            UpstreamEntry(name="anthropic", path=".anthropics-skills", url="https://github.com/a/b.git")
        ]
        forwards = [
            ForwardRule(**{"from": ".anthropics-skills/skills", "to": "skills/storage/anthropic", "enabled": False})
        ]

        status_output = " M skills/storage/anthropic/pdf/SKILL.md\n"

        svc = CommitService(repo_root=repo_root)
        upstream_changes, manual_changes = svc.classify(status_output, forwards, upstreams)

        assert upstream_changes == {}
        assert manual_changes == ["skills/storage/anthropic/pdf/SKILL.md"]

    def test_explicit_upstream_in_forward_rule(self):
        repo_root = "/home/user/project"
        upstreams = [
            UpstreamEntry(name="custom-up", path=".data/custom", url="https://github.com/a/b.git")
        ]
        forwards = [
            ForwardRule(**{
                "from": "arbitrary/source/path",
                "to": "skills/storage/custom",
                "upstream": "custom-up",
                "enabled": True,
            })
        ]

        status_output = " M skills/storage/custom/SKILL.md\n"
        svc = CommitService(repo_root=repo_root)
        upstream_changes, manual_changes = svc.classify(status_output, forwards, upstreams)

        assert "custom-up" in upstream_changes
        assert upstream_changes["custom-up"] == ["skills/storage/custom/SKILL.md"]
        assert manual_changes == []


class TestCommitAndPush:
    """Tests for commit_and_push execution."""

    @pytest.fixture()
    def git_repo(self, tmp_path):
        """Create a clean git repo with initial commit."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=str(repo), capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(repo), capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), capture_output=True, check=True)

        (repo / "README.md").write_text("# Test Repo")
        subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), capture_output=True, check=True)
        return repo

    def test_commit_manual_changes(self, git_repo):
        manual_file = git_repo / "skills" / "my_skills" / "SKILL.md"
        manual_file.parent.mkdir(parents=True)
        manual_file.write_text("my manual skill")

        messages = CommitMessages(
            manual="chore: manual update of {count} file(s) [{datetime}]",
            upstreams={"default": "sync: update from {upstream_name} [{datetime}]"}
        )

        svc = CommitService(repo_root=str(git_repo))
        success = svc.commit_and_push(
            upstream_changes={},
            manual_changes=["skills/my_skills/SKILL.md"],
            branch="main",
            current_time="2026-09-07 00:00",
            commit_messages=messages,
            auto_push=False,
        )
        assert success is True

        log_res = subprocess.run(
            ["git", "log", "-n", "1", "--format=%s"],
            cwd=str(git_repo), capture_output=True, text=True, check=True
        )
        assert "chore: manual update of 1 file(s) [2026-09-07 00:00]" in log_res.stdout

    def test_commit_upstream_and_manual_separate_commits(self, git_repo):
        up_file = git_repo / "skills" / "storage" / "anthropic" / "a.txt"
        up_file.parent.mkdir(parents=True)
        up_file.write_text("upstream content")

        manual_file = git_repo / "skills" / "storage" / "my_skills" / "b.txt"
        manual_file.parent.mkdir(parents=True)
        manual_file.write_text("manual content")

        messages = CommitMessages(
            manual="chore: manual update of {count} file(s) [{datetime}]",
            upstreams={"anthropic": "sync: auto-update from {upstream_name} [{datetime}]"}
        )

        svc = CommitService(repo_root=str(git_repo))
        success = svc.commit_and_push(
            upstream_changes={"anthropic": ["skills/storage/anthropic/a.txt"]},
            manual_changes=["skills/storage/my_skills/b.txt"],
            branch="main",
            current_time="2026-09-07 00:00",
            commit_messages=messages,
            auto_push=False,
        )
        assert success is True

        log_res = subprocess.run(
            ["git", "log", "-n", "2", "--format=%s"],
            cwd=str(git_repo), capture_output=True, text=True, check=True
        )
        logs = log_res.stdout.strip().splitlines()
        assert "chore: manual update of 1 file(s) [2026-09-07 00:00]" in logs[0]
        assert "sync: auto-update from anthropic [2026-09-07 00:00]" in logs[1]

    def test_clean_repo_returns_true(self, git_repo):
        messages = CommitMessages()
        svc = CommitService(repo_root=str(git_repo))
        success = svc.commit_and_push(
            upstream_changes={},
            manual_changes=[],
            branch="main",
            current_time="2026-09-07 00:00",
            commit_messages=messages,
            auto_push=False,
        )
        assert success is True

    def test_commit_staged_deletion_without_crashing_git_add(self, git_repo):
        del_file = git_repo / "skills" / "storage" / "affaan" / ".gitignore"
        del_file.parent.mkdir(parents=True)
        del_file.write_text("*.pyc")

        subprocess.run(["git", "add", "."], cwd=str(git_repo), check=True)
        subprocess.run(["git", "commit", "-m", "add gitignore"], cwd=str(git_repo), check=True)

        # Simulate prune: git rm --cached and delete from disk
        subprocess.run(
            ["git", "rm", "-f", "--cached", "--quiet", "skills/storage/affaan/.gitignore"],
            cwd=str(git_repo), check=True
        )
        del_file.unlink()

        messages = CommitMessages(
            upstreams={"affaan": "sync: auto-update from {upstream_name} [{datetime}]"}
        )

        svc = CommitService(repo_root=str(git_repo))
        success = svc.commit_and_push(
            upstream_changes={"affaan": ["skills/storage/affaan/.gitignore"]},
            manual_changes=[],
            branch="main",
            current_time="2026-09-08 00:00",
            commit_messages=messages,
            auto_push=False,
        )
        assert success is True

        log_res = subprocess.run(
            ["git", "log", "-n", "1", "--format=%s"],
            cwd=str(git_repo), capture_output=True, text=True, check=True
        )
        assert "sync: auto-update from affaan [2026-09-08 00:00]" in log_res.stdout

