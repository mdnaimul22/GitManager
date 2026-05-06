"""
Low-level Git subprocess wrapper. No business logic — pure command execution.
"""

from __future__ import annotations

import subprocess


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
        return False, (r.stderr.strip() or r.stdout.strip())
    except subprocess.TimeoutExpired:
        return False, f"git timed out after {timeout}s"
    except Exception as exc:
        logger.error(f"Git command failed: {exc}")
        return False, str(exc)


def repo_is_dirty(repo_path: str, logger: object) -> bool:
    """Check if a repo has uncommitted changes."""
    ok, out = run_git(["status", "--porcelain"], repo_path, logger)
    return ok and bool(out.strip())


def get_status(repo_path: str, logger: object) -> tuple[bool, str]:
    """Get git status --porcelain output."""
    return run_git(["status", "--porcelain"], repo_path, logger)
