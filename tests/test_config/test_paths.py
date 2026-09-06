"""
Config Paths API unit tests.

Covers:
- PROJECT_ROOT detection
- get_abs_path string conversion
"""

import pytest
from src.config import PROJECT_ROOT, get_abs_path


class TestPaths:
    """Tests for project root detection and path conversions."""

    def test_project_root_exists(self):
        assert PROJECT_ROOT.exists()
        assert (PROJECT_ROOT / "main.py").exists()

    def test_get_abs_path_resolves_correctly(self):
        abs_p = get_abs_path("main.py")
        assert abs_p.startswith("/")
        assert abs_p.endswith("main.py")


class TestPathSandboxing:
    """Unit tests for path sandboxing and security validations."""

    def test_safe_path_under_user_home(self):
        from src.config import is_path_sandboxed, assert_path_sandboxed, USER_HOME
        safe_path = f"{USER_HOME}/my_projects/test_repo"
        safe, msg = is_path_sandboxed(safe_path)
        assert safe is True
        assert msg == ""

        resolved = assert_path_sandboxed(safe_path)
        assert str(resolved) == safe_path

    def test_safe_path_under_tmp(self):
        from src.config import is_path_sandboxed, assert_path_sandboxed
        safe_path = "/tmp/test_workspace/my_repo"
        safe, msg = is_path_sandboxed(safe_path)
        assert safe is True

        resolved = assert_path_sandboxed(safe_path)
        assert str(resolved) == safe_path

    def test_safe_relative_path_with_base_root(self):
        from src.config import is_path_sandboxed, assert_path_sandboxed, PROJECT_ROOT
        safe, msg = is_path_sandboxed("src/config/paths.py", base_root=PROJECT_ROOT)
        assert safe is True

        resolved = assert_path_sandboxed("src/config/paths.py", base_root=PROJECT_ROOT)
        assert (PROJECT_ROOT / "src/config/paths.py").resolve() == resolved

    def test_empty_or_whitespace_path_rejected(self):
        from src.config import is_path_sandboxed, assert_path_sandboxed
        safe, msg = is_path_sandboxed("")
        assert safe is False
        assert "empty" in msg

        with pytest.raises(ValueError, match="empty"):
            assert_path_sandboxed("   ")

    def test_root_filesystem_rejected(self):
        from src.config import is_path_sandboxed, assert_path_sandboxed
        safe, msg = is_path_sandboxed("/")
        assert safe is False
        assert "Root filesystem" in msg

        with pytest.raises(ValueError, match="Root filesystem"):
            assert_path_sandboxed("/")

    def test_tmp_root_rejected(self):
        from src.config import is_path_sandboxed, assert_path_sandboxed
        safe, msg = is_path_sandboxed("/tmp")
        assert safe is False
        assert "/tmp" in msg

        with pytest.raises(ValueError, match="/tmp"):
            assert_path_sandboxed("/tmp")

    def test_user_home_root_rejected(self):
        from src.config import is_path_sandboxed, assert_path_sandboxed, USER_HOME
        safe, msg = is_path_sandboxed(str(USER_HOME))
        assert safe is False
        assert "User home directory" in msg

        with pytest.raises(ValueError, match="User home directory"):
            assert_path_sandboxed(str(USER_HOME))

    @pytest.mark.parametrize("forbidden_dir", [
        "/etc",
        "/etc/passwd",
        "/etc/cron.d",
        "/bin",
        "/bin/sh",
        "/usr",
        "/usr/bin",
        "/var",
        "/var/log",
        "/root",
    ])
    def test_forbidden_system_directories_rejected(self, forbidden_dir):
        from src.config import is_path_sandboxed, assert_path_sandboxed
        safe, msg = is_path_sandboxed(forbidden_dir)
        assert safe is False
        assert "forbidden system directory" in msg

        with pytest.raises(ValueError, match="forbidden system directory"):
            assert_path_sandboxed(forbidden_dir)

    @pytest.mark.parametrize("sensitive_file", [
        "~/.ssh",
        "~/.ssh/id_rsa",
        "~/.bashrc",
        "~/.gnupg",
        "~/.profile",
        "~/.aws",
        "~/.gitconfig",
    ])
    def test_sensitive_user_files_rejected(self, sensitive_file):
        from src.config import is_path_sandboxed, assert_path_sandboxed
        safe, msg = is_path_sandboxed(sensitive_file)
        assert safe is False
        assert "sensitive user configuration" in msg

        with pytest.raises(ValueError, match="sensitive user configuration"):
            assert_path_sandboxed(sensitive_file)

    def test_path_traversal_escaping_base_root_rejected(self):
        from src.config import is_path_sandboxed, assert_path_sandboxed, PROJECT_ROOT
        traversal = "../../../../../etc/passwd"
        safe, msg = is_path_sandboxed(traversal, base_root=PROJECT_ROOT)
        assert safe is False
        assert "escapes sandbox base" in msg

        with pytest.raises(ValueError, match="escapes sandbox base"):
            assert_path_sandboxed(traversal, base_root=PROJECT_ROOT)
