"""
Git Provider unit tests.

Covers:
- run_git basic execution
- run_git auto-recovery when stale index.lock exists
"""

import os
import time
import subprocess
from src.config import setup_logger, Settings
from src.providers.git import run_git, repo_is_dirty, get_status

logger = setup_logger(Settings.LOG_DIR / "service.log", name="gitmanager.tests.git_provider")


def test_run_git_success(tmp_path):
    repo_dir = str(tmp_path / "repo")
    os.makedirs(repo_dir, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)

    ok, out = run_git(["status"], repo_dir, logger)
    assert ok is True
    assert "On branch" in out


def test_run_git_clears_stale_index_lock(tmp_path):
    repo_dir = str(tmp_path / "repo_lock")
    os.makedirs(repo_dir, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_dir, check=True)

    # Create dummy file
    with open(os.path.join(repo_dir, "file.txt"), "w") as f:
        f.write("test content")

    # Simulate a stale index.lock file (abandoned 10 seconds ago)
    lock_file = os.path.join(repo_dir, ".git", "index.lock")
    with open(lock_file, "w") as f:
        f.write("")
    old_time = time.time() - 10
    os.utime(lock_file, (old_time, old_time))

    assert os.path.exists(lock_file)

    # run_git add should detect stale lock, clear it, and succeed
    ok, out = run_git(["add", "."], repo_dir, logger)
    assert ok is True
    assert not os.path.exists(lock_file)
