"""
Skill path forwarding and orphan cleanup service.
"""

import shutil

from src.config import (
    Settings, setup_logger, get_abs_path, get_mtime,
    read_json, write_json, exists, is_file, is_dir, ensure_dir, delete,
)
from src.schema import ForwardRule

logger = setup_logger(Settings.LOG_DIR / "service.log", name="gitmanager.services.forward")


def load_registry(rel: str) -> set[str]:
    """Load the set of managed skill destination paths from JSON."""
    if not exists(rel):
        return set()
    try:
        return set(read_json(rel))
    except Exception:
        return set()


def save_registry(paths: set[str], rel: str) -> None:
    """Save the set of managed skill destination paths to JSON."""
    parent = rel.rsplit("/", 1)[0]
    ensure_dir(parent)
    write_json(rel, sorted(list(paths)))


def _copy_if_newer(src_path: str, dst_path: str) -> bool:
    """Copy src to dst only if src is newer. Returns True if copied."""
    if exists(dst_path):
        if get_mtime(src_path) <= get_mtime(dst_path):
            return False

    shutil.copy2(get_abs_path(src_path), get_abs_path(dst_path))
    return True


def _incremental_copy_function(src: str, dst: str) -> str:
    """shutil.copytree copy_function — skips unchanged files.

    Uses config API (exists, is_file, get_mtime) which handles absolute paths.
    """
    if is_file(src) and is_file(dst):
        if get_mtime(src) <= get_mtime(dst):
            return dst
    return shutil.copy2(src, dst)


def forward_skills(
    forwards: list[ForwardRule],
) -> tuple[list[str], set[str]]:
    """
    Copy files/dirs from source to destination per forwarding rules.
    Uses mtime-based incremental copy to avoid redundant I/O.

    Returns:
        copied: list of names that were copied
        touched_dsts: set of relative destination paths (for orphan tracking)
    """
    copied: list[str] = []
    touched_dsts: set[str] = set()

    project_root = get_abs_path()

    for rule in forwards:
        if not rule.enabled:
            continue

        src = rule.from_path
        dst = rule.to_path
        name = src.rsplit("/", 1)[-1]

        if not exists(src):
            logger.warning(f"  ⚠️  Source missing — skipping: {src}")
            continue

        # Record destination as managed (relative to project root if possible)
        abs_dst = get_abs_path(dst)
        abs_root = get_abs_path()
        if abs_dst.startswith(abs_root + "/"):
            touched_dsts.add(abs_dst[len(abs_root) + 1:])
        else:
            touched_dsts.add(abs_dst)

        logger.info(f"  Forwarding [{name}] …")
        try:
            if is_file(src):
                if is_dir(dst) or dst.endswith("/") or dst.endswith("\\"):
                    ensure_dir(dst)
                    actual_dst = f"{dst}/{name}"
                else:
                    parent = dst.rsplit("/", 1)[0]
                    ensure_dir(parent)
                    actual_dst = dst

                if _copy_if_newer(src, actual_dst):
                    logger.info(f"     ✅  [File] {src} → {actual_dst}")
                    copied.append(name)
                else:
                    logger.debug(f"     ⏭  [File] {name} — unchanged, skipped")

            elif is_dir(src):
                ensure_dir(dst)
                shutil.copytree(
                    src, dst,
                    dirs_exist_ok=True,
                    copy_function=_incremental_copy_function,
                )
                logger.info(f"     ✅  [Dir]  {src} → {dst}")
                copied.append(name)

        except Exception as exc:
            logger.error(f"     ✗  {exc}")

    return copied, touched_dsts


def cleanup_orphans(
    previous_managed: set[str],
    current_managed: set[str],
    repo_root: str = "",
) -> list[str]:
    """
    Remove destination paths that were previously managed but are no longer
    in the current forwarding config.

    Uses TWO detection strategies:
      1. Memory diff: previous_managed - current_managed
      2. Disk scan: items on disk in known destination dirs but NOT in current_managed

    Strategy 2 catches orphans that were already committed to git before the
    forward rule was removed (the root cause of the ghost skill bug).

    Also removes from git index if repo_root is provided, preventing
    git pull from restoring deleted paths.

    Returns:
        removed: list of names that were cleaned up
    """
    removed: list[str] = []

    # Strategy 1: Memory-based diff
    orphans = previous_managed - current_managed

    # Strategy 2: Disk scan — find items on disk that shouldn't exist
    # Collect all unique destination parent dirs from current_managed
    dest_parents: set[str] = set()
    for path in current_managed | previous_managed:
        parent = path.rsplit("/", 1)[0]
        if parent:
            dest_parents.add(parent)

    for parent_dir in dest_parents:
        if not is_dir(parent_dir):
            continue
        from src.config import list_files
        for child in list_files(parent_dir, "*"):
            if not child.is_dir():
                continue
            child_abs = str(child)
            if child_abs not in current_managed:
                orphans.add(child_abs)

    for orphan_rel in orphans:
        if exists(orphan_rel):
            name = orphan_rel.rsplit("/", 1)[-1]
            logger.warning(f"  🗑️  Removing orphaned upstream skill: {name}")
            try:
                # Remove from git index first (prevents git pull from restoring)
                if repo_root:
                    import subprocess
                    subprocess.run(
                        ["git", "rm", "-r", "--cached", "--quiet", orphan_rel],
                        cwd=repo_root,
                        capture_output=True,
                        timeout=10,
                    )
                # Then remove from disk
                delete(orphan_rel)
                removed.append(name)
                logger.info(f"     ✅  Removed orphan: {name}")
            except Exception as exc:
                logger.error(f"     ✗  Failed to remove {name}: {exc}")

    return removed
