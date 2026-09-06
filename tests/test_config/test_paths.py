"""
Config Paths API unit tests.

Covers:
- PROJECT_ROOT detection
- get_abs_path string conversion
"""

import pytest
import src.config
from src.config import get_abs_path
from src.config.paths import PROJECT_ROOT, resolve_sandboxed


class TestPaths:
    """Tests for project root detection and path conversions."""

    def test_project_root_not_exported_in_public_config_all(self):
        """PROJECT_ROOT must be private to paths.py and not exposed in public config API."""
        assert "PROJECT_ROOT" not in src.config.__all__

    def test_project_root_exists(self):
        assert PROJECT_ROOT.exists()
        assert (PROJECT_ROOT / "main.py").exists()

    def test_get_abs_path_resolves_correctly(self):
        abs_p = get_abs_path("main.py")
        assert abs_p.startswith("/")
        assert abs_p.endswith("main.py")


class TestPathSandboxing:
    """Unit tests for internal path sandboxing and security validations."""

    def test_safe_relative_path_within_project_root(self):
        resolved = resolve_sandboxed("src/config/paths.py")
        assert (PROJECT_ROOT / "src/config/paths.py").resolve() == resolved

    def test_safe_path_under_tmp_during_tests(self):
        resolved = resolve_sandboxed("/tmp/test_workspace/my_repo")
        assert str(resolved) == "/tmp/test_workspace/my_repo"

    def test_empty_or_whitespace_path_rejected(self):
        with pytest.raises(ValueError, match="empty"):
            resolve_sandboxed("")

        with pytest.raises(ValueError, match="empty"):
            resolve_sandboxed("   ")

    def test_null_byte_path_rejected(self):
        with pytest.raises(ValueError, match="Null bytes not permitted"):
            resolve_sandboxed("data/projects.json\0/../../etc/passwd")

    def test_path_traversal_escaping_project_root_rejected(self):
        traversal = "../../../../../etc/passwd"
        with pytest.raises(ValueError, match="escapes PROJECT_ROOT sandbox"):
            resolve_sandboxed(traversal)

    def test_forbidden_system_directory_rejected(self):
        with pytest.raises(ValueError, match="escapes PROJECT_ROOT sandbox"):
            resolve_sandboxed("/etc/passwd")

    def test_sensitive_user_file_rejected(self):
        with pytest.raises(ValueError, match="escapes PROJECT_ROOT sandbox"):
            resolve_sandboxed("~/.ssh/id_rsa")
