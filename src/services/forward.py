"""
Skill path forwarding and orphan cleanup service.
"""

import shutil

from src.config import (
    Settings, setup_logger, get_abs_path,
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


def forward_skills(
    forwards: list[ForwardRule],
) -> tuple[list[str], set[str]]:
    """
    Copy files/dirs from source to destination per forwarding rules.

    Returns:
        copied: list of names that were copied
        touched_dsts: set of relative destination paths (for orphan tracking)
    """
    copied: list[str] = []
    cleared_dsts: set[str] = set()
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

                shutil.copy2(src, actual_dst)
                logger.info(f"     ✅  [File] {src} → {actual_dst}")
                copied.append(name)

            elif is_dir(src):
                resolved_dst = get_abs_path(dst)
                if resolved_dst not in cleared_dsts:
                    if exists(dst):
                        delete(dst)
                    cleared_dsts.add(resolved_dst)

                shutil.copytree(src, dst, dirs_exist_ok=True)
                logger.info(f"     ✅  [Dir]  {src} → {dst}")
                copied.append(name)

        except Exception as exc:
            logger.error(f"     ✗  {exc}")

    return copied, touched_dsts


def cleanup_orphans(
    previous_managed: set[str],
    current_managed: set[str],
) -> list[str]:
    """
    Remove destination paths that were previously managed but are no longer
    in the current forwarding config.

    Returns:
        removed: list of names that were cleaned up
    """
    removed: list[str] = []
    orphans = previous_managed - current_managed

    for orphan_rel in orphans:
        if exists(orphan_rel):
            name = orphan_rel.rsplit("/", 1)[-1]
            logger.warning(f"  🗑️  Removing orphaned upstream skill: {name}")
            try:
                delete(orphan_rel)
                removed.append(name)
            except Exception as exc:
                logger.error(f"     ✗  Failed to remove {name}: {exc}")

    return removed
