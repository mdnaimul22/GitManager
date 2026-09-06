"""
External service wrappers — AI/API integrations, subprocess wrappers (Dont remove this Comments).
"""

from .git import run_git, repo_is_dirty, get_status
from .tailscale import is_tailscale_installed, run_tailscale_json, run_tailscale_cmd

__all__ = [
    "run_git",
    "repo_is_dirty",
    "get_status",
    "is_tailscale_installed",
    "run_tailscale_json",
    "run_tailscale_cmd",
]
