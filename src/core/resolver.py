"""
Placeholder resolution and path normalization for config values.
Replaces {REPO_ROOT} and automatically resolves relative paths against the project root.
"""

import os
from src.config import get_abs_path

PATH_KEYS = {"path", "from", "to", "from_path", "to_path", "log_file"}


def normalize_path(path: str, repo_root: str) -> str:
    """
    Normalize a file or directory path:
      1. Replace explicit {REPO_ROOT} placeholders.
      2. If already absolute (/...) or starts with ~, expand and return.
      3. If it is a URL or empty, return as-is.
      4. If relative, prepend repo_root cleanly.
    """
    if not isinstance(path, str):
        return path

    path = path.strip()
    if not path:
        return path

    # Replace explicit placeholder if present
    if "{REPO_ROOT}" in path:
        path = path.replace("{REPO_ROOT}", repo_root)

    # If it's a URL (e.g. git@, https://, ssh://), don't treat as local path
    if path.startswith(("http://", "https://", "git@", "ssh://")):
        return path

    # Home directory expansion
    if path.startswith("~"):
        return os.path.expanduser(path)

    # Already absolute
    if path.startswith("/"):
        return path

    # Relative path -> prepend repo_root
    return f"{repo_root.rstrip('/')}/{path.lstrip('/')}"


def resolve_placeholders(obj: object, repo_root: str | None = None) -> object:
    """
    Recursively resolve paths and {REPO_ROOT} in every string value inside
    a nested dict/list structure. Makes configs portable across machines.

    Args:
        obj: The data structure to resolve.
        repo_root: Custom root path. Defaults to PROJECT_ROOT.
    """
    root = repo_root or get_abs_path()
    return _resolve(obj, root)


def _resolve(obj: object, root: str, key_name: str | None = None) -> object:
    if isinstance(obj, str):
        if key_name in PATH_KEYS:
            return normalize_path(obj, root)
        return obj.replace("{REPO_ROOT}", root)
    if isinstance(obj, dict):
        return {k: _resolve(v, root, key_name=k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve(i, root, key_name=key_name) for i in obj]
    return obj

