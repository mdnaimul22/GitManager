"""
Core Resolver unit tests.

Covers:
- normalize_path: relative path, nested relative, absolute unchanged, {REPO_ROOT} placeholder
- resolve_placeholders: recursive resolution on config dicts preserving non-path values
"""

import pytest
from src.core.resolver import normalize_path, resolve_placeholders


class TestSmartPathResolution:
    """Automatic path normalization for relative, absolute, and template paths."""

    def test_normalize_relative_path(self):
        res = normalize_path(".anthropics-skills", "/home/user/project")
        assert res == "/home/user/project/.anthropics-skills"

    def test_normalize_nested_relative_path(self):
        res = normalize_path("skills/storage/anthropics_skills", "/home/user/project")
        assert res == "/home/user/project/skills/storage/anthropics_skills"

    def test_normalize_absolute_path_unchanged(self):
        res = normalize_path("/opt/custom/path", "/home/user/project")
        assert res == "/opt/custom/path"

    def test_normalize_repo_root_placeholder(self):
        res = normalize_path("{REPO_ROOT}/skills", "/home/user/project")
        assert res == "/home/user/project/skills"

    def test_resolve_placeholders_dict(self):
        raw_config = {
            "name": "anthropics-skills",
            "path": ".anthropics-skills",
            "url": "https://github.com/anthropics/skills.git",
            "branch": "main",
            "forwards": [
                {"from": ".anthropics-skills/skills", "to": "skills/storage", "enabled": True}
            ],
            "messages": "chore: {count} files",
        }
        resolved = resolve_placeholders(raw_config, repo_root="/home/user/project")

        # Path keys must be normalized with repo_root
        assert resolved["path"] == "/home/user/project/.anthropics-skills"
        assert resolved["forwards"][0]["from"] == "/home/user/project/.anthropics-skills/skills"
        assert resolved["forwards"][0]["to"] == "/home/user/project/skills/storage"

        # Non-path keys must NOT be corrupted
        assert resolved["name"] == "anthropics-skills"
        assert resolved["url"] == "https://github.com/anthropics/skills.git"
        assert resolved["branch"] == "main"
        assert resolved["messages"] == "chore: {count} files"
