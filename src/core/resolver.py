"""
Placeholder resolution for config values.
Replaces {REPO_ROOT} and other template variables.
"""

from src.config import get_abs_path


def resolve_placeholders(obj: object, repo_root: str | None = None) -> object:
    """
    Recursively replace {REPO_ROOT} in every string value inside
    a nested dict/list structure. Makes configs portable across machines.

    Args:
        obj: The data structure to resolve.
        repo_root: Custom root path. Defaults to PROJECT_ROOT.
    """
    root = repo_root or get_abs_path()
    return _resolve(obj, root)


def _resolve(obj: object, root: str) -> object:
    if isinstance(obj, str):
        return obj.replace("{REPO_ROOT}", root)
    if isinstance(obj, dict):
        return {k: _resolve(v, root) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve(i, root) for i in obj]
    return obj
