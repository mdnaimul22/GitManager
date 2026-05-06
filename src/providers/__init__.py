"""
External service wrappers — AI/API integrations, subprocess wrappers (Dont remove this Comments).
"""

from .git import run_git, repo_is_dirty, get_status

__all__ = ["run_git", "repo_is_dirty", "get_status"]
