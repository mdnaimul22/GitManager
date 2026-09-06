"""
Config module entry point.
Auto-loads environment variables and exports all configuration utilities.
"""

from .paths import (
    PROJECT_ROOT,
    USER_HOME,
    FORBIDDEN_SYSTEM_ROOTS,
    FORBIDDEN_USER_NAMES,
    find_project_root,
    is_path_sandboxed,
    assert_path_sandboxed,
)
from .files import (
    read_text, write_text, read_json, write_json,
    exists, is_file, is_dir, ensure_dir, delete, list_files,
    get_abs_path, get_mtime,
)
from .dotenv import load_dotenv, set_value, get_value, remove_value
from .settings import Settings
from .logger import setup_logger, shutdown

# Auto-load environment variables on import
load_dotenv()

__all__ = [
    "PROJECT_ROOT",
    "USER_HOME",
    "FORBIDDEN_SYSTEM_ROOTS",
    "FORBIDDEN_USER_NAMES",
    "find_project_root",
    "is_path_sandboxed",
    "assert_path_sandboxed",
    "read_text",
    "write_text",
    "read_json",
    "write_json",
    "exists",
    "is_file",
    "is_dir",
    "ensure_dir",
    "delete",
    "list_files",
    "get_abs_path",
    "get_mtime",
    "load_dotenv",
    "set_value",
    "get_value",
    "remove_value",
    "Settings",
    "setup_logger",
    "shutdown",
]