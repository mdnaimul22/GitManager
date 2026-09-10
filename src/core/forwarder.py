"""
Forwarding and auto-prune domain engine.

Pure business logic for:
- Evaluating incremental copy requirements (mtime comparisons).
- Auto-prune mirroring calculations (finding extraneous files and directory drifts).
- Memory entry state snapshot construction.
"""

import os
import shutil
from src.config import (
    Settings, setup_logger, get_abs_path, get_rel_path, get_mtime,
    exists, is_file, is_dir, ensure_dir, delete,
)
from src.helpers import time_now_iso
from src.schema import ForwardRule, MemoryEntry, generate_hash_id

logger = setup_logger(Settings.LOG_DIR / "core.log", name="gitmanager.core.forwarder")


class ForwardEngine:
    """
    Evaluates source-to-destination mirroring rules.
    Decides what to copy, what to prune, and records immutable memory records.
    """

    def __init__(self, repo_root: str = "") -> None:
        self.repo_root = repo_root

    @staticmethod
    def should_copy(src_path: str, dst_path: str) -> bool:
        """Evaluate if src_path should be copied to dst_path based on mtime."""
        if exists(dst_path):
            if get_mtime(src_path) <= get_mtime(dst_path):
                return False
        return True

    @staticmethod
    def ignore_copy_patterns(path: str, names: list[str]) -> set[str]:
        """Safety guard: Never copy .git or VCS folders into destination skills."""
        ignored = set()
        if ".git" in names:
            ignored.add(".git")
        return ignored

    @staticmethod
    def incremental_copy(src: str, dst: str) -> str:
        """Copy file skipping if unchanged."""
        if is_file(src) and is_file(dst):
            if get_mtime(src) <= get_mtime(dst):
                return dst
        return shutil.copy2(src, dst)

    def prune_extraneous(self, src_dir: str, dst_dir: str) -> list[str]:
        """
        Calculates and removes extraneous files/directories from dst_dir that
        do not exist in src_dir, ensuring exact mirror alignment.
        Returns list of deleted relative paths.
        """
        abs_src = get_abs_path(src_dir)
        abs_dst = get_abs_path(dst_dir)

        if not exists(abs_dst):
            return []

        pruned: list[str] = []

        # Remove top-level .git if present
        git_dir = f"{abs_dst}/.git"
        if exists(git_dir):
            delete(git_dir)
            pruned.append(get_rel_path(git_dir, self.repo_root) if self.repo_root else git_dir)

        for root, dirs, files in os.walk(abs_dst, topdown=True):
            rel_to_dst = get_rel_path(root, abs_dst)
            src_dir_equiv = abs_src if rel_to_dst in (".", "") else f"{abs_src}/{rel_to_dst}"

            # 1. Clean extraneous files
            for f in files:
                dst_file = f"{root}/{f}"
                src_file = f"{src_dir_equiv}/{f}"
                if not exists(src_file):
                    try:
                        delete(dst_file)
                        pruned.append(get_rel_path(dst_file, self.repo_root) if self.repo_root else dst_file)
                    except Exception as e:
                        logger.debug(f"Failed to prune file {dst_file}: {e}")

            # 2. Clean extraneous directories or forbidden .git directories
            removable_dirs = []
            for d in dirs:
                if d == ".git":
                    removable_dirs.append(d)
                    continue
                dst_subdir = f"{root}/{d}"
                src_subdir = f"{src_dir_equiv}/{d}"
                if not exists(src_subdir):
                    removable_dirs.append(d)

            for d in removable_dirs:
                dst_subdir = f"{root}/{d}"
                try:
                    delete(dst_subdir)
                    pruned.append(get_rel_path(dst_subdir, self.repo_root) if self.repo_root else dst_subdir)
                except Exception as e:
                    logger.debug(f"Failed to prune directory {dst_subdir}: {e}")
                dirs.remove(d)

        return pruned

    def create_memory_entry(self, rule: ForwardRule) -> MemoryEntry:
        """Create a clean state memory record for a forwarding rule."""
        mem_from = get_rel_path(rule.from_path, self.repo_root)
        mem_to = get_rel_path(rule.to_path, self.repo_root)
        return MemoryEntry(
            memory_id=generate_hash_id(),
            upstream_id=rule.upstream_id,
            forward_id=rule.forward_id,
            project_name=rule.project_name,
            from_path=mem_from,
            to_path=mem_to,
            last_synced=time_now_iso(),
        )
