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
