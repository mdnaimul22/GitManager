"""
Config Files API unit tests.

Covers:
- exists, read_text, read_json, write_text, write_json, ensure_dir, delete, list_files, get_mtime
"""

import os
import tempfile
import time
import pytest
from src.config import (
    exists,
    read_text,
    read_json,
    write_text,
    write_json,
    ensure_dir,
    delete,
    get_mtime,
    get_abs_path,
    get_rel_path,
)


class TestFileOperations:
    """Unit tests for config filesystem wrapper functions."""

    def test_get_mtime_returns_valid_timestamp(self):
        mtime = get_mtime("main.py")
        assert isinstance(mtime, float)
        assert mtime > 0

    def test_get_mtime_with_absolute_path(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"test")
            tmp = f.name
        try:
            mtime = get_mtime(tmp)
            assert isinstance(mtime, float)
            assert mtime > 0
        finally:
            os.unlink(tmp)

    def test_get_mtime_increases_after_write(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"v1")
            tmp = f.name
        try:
            mtime1 = get_mtime(tmp)
            time.sleep(0.05)
            with open(tmp, "w") as f:
                f.write("v2")
            mtime2 = get_mtime(tmp)
            assert mtime2 >= mtime1
        finally:
            os.unlink(tmp)

    def test_read_and_write_json_roundtrip(self, tmp_path):
        target = str(tmp_path / "data.json")
        sample_data = {"name": "test", "items": [1, 2, 3]}
        write_json(target, sample_data)
        assert exists(target)

        loaded = read_json(target)
        assert loaded == sample_data

    def test_read_and_write_text_roundtrip(self, tmp_path):
        target = str(tmp_path / "test.txt")
        write_text(target, "hello world")
        assert exists(target)
        assert read_text(target) == "hello world"

    def test_delete_file_and_directory(self, tmp_path):
        target_dir = tmp_path / "sub"
        target_file = target_dir / "sample.txt"
        ensure_dir(str(target_dir))
        write_text(str(target_file), "content")
        assert exists(str(target_file))

        delete(str(target_file))
        assert not exists(str(target_file))

        delete(str(target_dir))
        assert not exists(str(target_dir))

    def test_file_operations_reject_path_traversal(self):
        with pytest.raises(ValueError, match="escapes PROJECT_ROOT sandbox"):
            read_text("../../../etc/passwd")

        with pytest.raises(ValueError, match="escapes PROJECT_ROOT sandbox"):
            write_text("../../../tmp/malicious.txt", "payload")

        with pytest.raises(ValueError, match="escapes PROJECT_ROOT sandbox"):
            get_abs_path("../../../etc")

    def test_file_operations_reject_forbidden_system_paths(self):
        with pytest.raises(ValueError, match="escapes PROJECT_ROOT sandbox"):
            read_text("/etc/passwd")

        with pytest.raises(ValueError, match="escapes PROJECT_ROOT sandbox"):
            write_text("/etc/malicious.txt", "payload")

        with pytest.raises(ValueError, match="escapes PROJECT_ROOT sandbox"):
            delete("/etc/some_file")

    def test_file_operations_reject_sensitive_user_paths(self):
        with pytest.raises(ValueError, match="escapes PROJECT_ROOT sandbox"):
            read_text("~/.ssh/id_rsa")

        with pytest.raises(ValueError, match="escapes PROJECT_ROOT sandbox"):
            write_text("~/.bashrc", "# hacked")

    def test_delete_prevents_self_destruction(self):
        with pytest.raises(ValueError, match="Cannot delete protected path"):
            delete(".")

        with pytest.raises(ValueError, match="Cannot delete protected path"):
            delete("src")

        with pytest.raises(ValueError, match="Cannot delete protected path"):
            delete(".git")

    def test_write_text_prevents_modifying_source_code(self):
        with pytest.raises(ValueError, match="modifying source directory is forbidden"):
            write_text("src/malicious.py", "# hack")


class TestGetRelPath:
    """Unit tests for get_rel_path relative path conversion utility."""

    def test_empty_path(self):
        assert get_rel_path("") == ""

    def test_already_relative_path(self):
        assert get_rel_path(".data/foo/skills") == ".data/foo/skills"
        assert get_rel_path("skills/storage/my_skill") == "skills/storage/my_skill"

    def test_absolute_path_under_project_root(self):
        abs_p = get_abs_path("skills/storage/agent-zero")
        assert get_rel_path(abs_p) == "skills/storage/agent-zero"

    def test_absolute_path_under_custom_base(self):
        base = "/home/user/project"
        abs_p = "/home/user/project/skills/storage/my_skill"
        assert get_rel_path(abs_p, base) == "skills/storage/my_skill"

    def test_path_outside_custom_base(self):
        base = "/home/user/project"
        outside_p = "/var/log/syslog"
        assert get_rel_path(outside_p, base) == "/var/log/syslog"

    def test_handles_trailing_slashes(self):
        base = "/home/user/project/"
        abs_p = "/home/user/project/skills/storage/demo/"
        # Resolving via Path or string stripping should produce clean relative path
        result = get_rel_path(abs_p, base)
        assert result in ("skills/storage/demo", "skills/storage/demo/")

