"""
Low-level Git subprocess wrapper. No business logic — pure command execution.
"""

from __future__ import annotations

import os
import time
import subprocess

from src.config import exists, delete, get_mtime


def _clean_stale_lock(err: str, cwd: str, logger: object) -> bool:
    """Detect and safely clear stale git lock file if present and older than threshold."""
    if "index.lock" not in err and ".lock': File exists" not in err:
        return False

    lock_file: str | None = None
    if "'" in err:
        for part in err.split("'"):
            if part.endswith(".lock"):
                lock_file = part
                break

    if not lock_file:
        candidate = f"{cwd}/.git/index.lock"
        if exists(candidate):
            lock_file = candidate

    if lock_file and exists(lock_file):
        try:
            mtime = get_mtime(lock_file)
            age = time.time() - mtime
            if age > 5:
                if hasattr(logger, "warning"):
                    logger.warning(f"Clearing stale git lock (age {age:.1f}s): {lock_file}")
                try:
                    delete(lock_file)
                except Exception:
                    os.remove(lock_file)
                return True
        except (OSError, ValueError) as e:
            if hasattr(logger, "warning"):
                logger.warning(f"Could not remove git lock file {lock_file}: {e}")
    return False


def run_git(
    args: list[str],
    cwd: str,
    logger: object,
    timeout: int = 120,
) -> tuple[bool, str]:
    """Execute a git command and return (success, output)."""
    try:
        r = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if r.returncode == 0:
            return True, r.stdout.strip()

        err = r.stderr.strip() or r.stdout.strip()
        if _clean_stale_lock(err, cwd, logger):
            r_retry = subprocess.run(
                ["git"] + args,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if r_retry.returncode == 0:
                return True, r_retry.stdout.strip()
            return False, (r_retry.stderr.strip() or r_retry.stdout.strip())

        return False, err
    except subprocess.TimeoutExpired:
        return False, f"git timed out after {timeout}s"
    except Exception as exc:
        if hasattr(logger, "error"):
            logger.error(f"Git command failed: {exc}")
        return False, str(exc)


def repo_is_dirty(repo_path: str, logger: object) -> bool:
    """Check if a repo has uncommitted changes."""
    ok, out = run_git(["status", "--porcelain"], repo_path, logger)
    return ok and bool(out.strip())


def get_status(repo_path: str, logger: object) -> tuple[bool, str]:
    """Get git status --porcelain output."""
    return run_git(["status", "--porcelain"], repo_path, logger)
