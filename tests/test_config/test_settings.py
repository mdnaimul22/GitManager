"""
Config Settings and Environment tests.

Covers:
- Settings properties and environment modes
- Gitignore data/ directory protection
"""

import subprocess
import pytest
from src.config import Settings, read_text, PROJECT_ROOT


class TestSettings:
    """Tests for application settings and configuration."""

    def test_settings_properties(self):
        assert Settings.PROJECT_NAME == "GitManager"
        assert isinstance(Settings.VERSION, str)
        assert isinstance(Settings.API_PORT, int)

    def test_data_in_gitignore(self):
        gitignore = read_text(".gitignore")
        assert "data/" in gitignore, "data/ must be in .gitignore"

    def test_data_not_tracked_by_git(self):
        result = subprocess.run(
            ["git", "ls-files", "--", "data/"],
            capture_output=True, text=True, timeout=5,
            cwd=str(PROJECT_ROOT),
        )
        tracked_files = result.stdout.strip()
        assert tracked_files == "", f"data/ files must not be git tracked: {tracked_files}"
