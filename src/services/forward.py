"""
Skill path forwarding, auto-prune mirroring, and structured memory lifecycle service.
"""

import os
import shutil
from typing import Any
from src.config import (
    Settings, setup_logger, get_abs_path, get_rel_path, get_mtime,
    read_json, write_json, exists, is_file, is_dir, ensure_dir, delete,
)
from src.helpers import time_now_iso
from src.providers import run_git
from src.schema import ForwardRule, MemoryEntry, UpstreamEntry, generate_hash_id

logger = setup_logger(Settings.LOG_DIR / "service.log", name="gitmanager.services.forward")


# ── Structured Memory Registry (CRUD) ──────────────────────────────────────────

def load_memory(rel: str) -> list[MemoryEntry]:
    """
    Load managed skill memory entries from JSON.

    Supports:
      - New structured format: list[dict] conforming to MemoryEntry
      - Legacy path lists: list[str] (destination paths)
      - Legacy dict containers: {"managed_skills": [...]} or {"entries": [...]}
    """
    if not exists(rel):
        return []
    try:
        raw = read_json(rel)
        if isinstance(raw, dict):
            raw = raw.get("entries") or raw.get("managed_skills") or []
        if not isinstance(raw, list):
            return []

        entries: list[MemoryEntry] = []
        for item in raw:
            if isinstance(item, dict):
                entries.append(MemoryEntry(**item))
            elif isinstance(item, str) and item.strip():
                entries.append(MemoryEntry(to_path=item.strip()))
        return entries
    except Exception as exc:
        logger.warning(f"Failed to parse memory from {rel}: {exc}")
        return []


def save_memory(entries: list[MemoryEntry], rel: str) -> None:
    """Save managed skill memory entries to JSON in structured format."""
    parent = rel.rsplit("/", 1)[0]
    ensure_dir(parent)
    data = [e.model_dump(by_alias=True) for e in entries]
    write_json(rel, data)


def load_registry(rel: str) -> set[str]:
    """Backward compatibility wrapper returning destination paths as a set."""
    entries = load_memory(rel)
    return {e.to_path for e in entries if e.to_path}


def save_registry(paths: set[str], rel: str) -> None:
    """Backward compatibility wrapper saving destination paths to memory."""
    existing = {e.to_path: e for e in load_memory(rel) if e.to_path}
    entries: list[MemoryEntry] = []
    for p in sorted(list(paths)):
        if p in existing:
            entries.append(existing[p])
        else:
            entries.append(MemoryEntry(to_path=p))
    save_memory(entries, rel)


# ── Copy & Prune Helpers ──────────────────────────────────────────────────────

def _copy_if_newer(src_path: str, dst_path: str) -> bool:
    """Copy src to dst only if src is newer. Returns True if copied."""
    if exists(dst_path):
        if get_mtime(src_path) <= get_mtime(dst_path):
            return False

    shutil.copy2(get_abs_path(src_path), get_abs_path(dst_path))
    return True


def _incremental_copy_function(src: str, dst: str) -> str:
    """shutil.copytree copy_function — skips unchanged files."""
    if is_file(src) and is_file(dst):
        if get_mtime(src) <= get_mtime(dst):
            return dst
    return shutil.copy2(src, dst)


def _ignore_copy_patterns(path: str, names: list[str]) -> set[str]:
    """Guard: Never copy .git or VCS folders into destination skills."""
    ignored = set()
    if ".git" in names:
        ignored.add(".git")
    return ignored


def _prune_extraneous(src_dir: str, dst_dir: str, repo_root: str = "") -> list[str]:
    """
    Auto-Prune Mirror: Remove files and subdirectories from dst_dir that
    do not exist in src_dir, and unconditionally remove forbidden .git folders.
    Mirrors 'rsync --delete' behavior.
    """
    abs_src = get_abs_path(src_dir)
    abs_dst = get_abs_path(dst_dir)

    if not exists(abs_dst):
        return []

    pruned: list[str] = []

    # Clean up top-level .git if present
    git_dir = f"{abs_dst}/.git"
    if exists(git_dir):
        delete(git_dir)
        pruned.append(git_dir)
        if repo_root:
            rel_repo = get_rel_path(git_dir, repo_root)
            run_git(["rm", "-r", "-f", "--cached", "--quiet", rel_repo], repo_root, logger)

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
                    pruned.append(dst_file)
                    if repo_root:
                        rel_repo = get_rel_path(dst_file, repo_root)
                        run_git(["rm", "-f", "--cached", "--quiet", rel_repo], repo_root, logger)
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
                pruned.append(dst_subdir)
                if repo_root:
                    rel_repo = get_rel_path(dst_subdir, repo_root)
                    run_git(["rm", "-r", "-f", "--cached", "--quiet", rel_repo], repo_root, logger)
            except Exception as e:
                logger.debug(f"Failed to prune directory {dst_subdir}: {e}")
            dirs.remove(d)

    return pruned


# ── Forwarding & Orphan Cleanup ───────────────────────────────────────────────

def _resolve_missing_source(
    src: str,
    rule: ForwardRule,
    upstreams: list[UpstreamEntry] | None = None,
    repo_root: str = "",
) -> bool:
    """
    Verify and dynamically checkout missing source path if it exists in an upstream repo.

    Returns:
        True if the path exists (or was dynamically checked out), False otherwise.
    """
    matched_upstream: UpstreamEntry | None = None
    if upstreams:
        if rule.upstream_id:
            for u in upstreams:
                if u.upstream_id == rule.upstream_id:
                    matched_upstream = u
                    break
        if not matched_upstream:
            for u in upstreams:
                up_abs = (
                    get_abs_path(repo_root, u.path)
                    if repo_root and not u.path.startswith("/")
                    else get_abs_path(u.path)
                )
                if src == up_abs or src.startswith(up_abs + "/"):
                    matched_upstream = u
                    break

    if not matched_upstream:
        logger.warning(f"  ⚠️  Source missing — skipping: {src}")
        return False

    up_abs = (
        get_abs_path(repo_root, matched_upstream.path)
        if repo_root and not matched_upstream.path.startswith("/")
        else get_abs_path(matched_upstream.path)
    )

    if not exists(up_abs):
        logger.warning(f"  ⚠️  Upstream repository path missing: {up_abs}")
        return False

    rel_in_upstream = get_rel_path(src, up_abs)

    # Check if path exists in upstream git tree
    ok_head, _ = run_git(["cat-file", "-e", f"HEAD:{rel_in_upstream}"], up_abs, logger)
    if not ok_head and matched_upstream.url and matched_upstream.branch:
        # Fetch latest changes from remote in case upstream remote updated
        fetch_cmd = ["fetch", "origin", matched_upstream.branch]
        if matched_upstream.blobless:
            fetch_cmd += ["--filter=blob:none"]
        run_git(fetch_cmd, up_abs, logger)
        ok_remote, _ = run_git(
            ["cat-file", "-e", f"origin/{matched_upstream.branch}:{rel_in_upstream}"],
            up_abs,
            logger,
        )
        if ok_remote:
            run_git(["reset", "--hard", f"origin/{matched_upstream.branch}"], up_abs, logger)
            ok_head = True

    if not ok_head:
        logger.warning(f"  ⚠️  UpStreaming Source file missing: {src}")
        return False

    # Path exists in upstream Git repository! Dynamically materialize it
    if matched_upstream.sparse:
        run_git(["sparse-checkout", "add", "--skip-checks", rel_in_upstream], up_abs, logger)
    else:
        run_git(["checkout", "HEAD", "--", rel_in_upstream], up_abs, logger)

    if exists(src):
        logger.info(f"  📥 Dynamically checked out missing upstream path: {rel_in_upstream}")
        return True

    logger.warning(f"  ⚠️  Source missing — skipping: {src}")
    return False


def forward_skills(
    forwards: list[ForwardRule],
    repo_root: str = "",
    upstreams: list[UpstreamEntry] | None = None,
) -> tuple[list[str], list[MemoryEntry]]:
    """
    Copy files/dirs from source to destination per forwarding rules.
    Applies Auto-Prune Mirroring so destination exactly reflects source.

    Returns:
        copied: list of names that were copied
        current_memory: list of MemoryEntry records for state tracking
    """
    copied: list[str] = []
    current_memory: list[MemoryEntry] = []

    now_iso = time_now_iso()

    for rule in forwards:
        if not rule.enabled:
            continue

        raw_src = rule.from_path
        raw_dst = rule.to_path
        name = raw_src.rsplit("/", 1)[-1]

        try:
            src = (
                get_abs_path(repo_root, raw_src)
                if repo_root and not raw_src.startswith("/")
                else get_abs_path(raw_src)
            )
            dst = (
                get_abs_path(repo_root, raw_dst)
                if repo_root and not raw_dst.startswith("/")
                else get_abs_path(raw_dst)
            )
        except Exception as exc:
            logger.warning(f"  ⚠️  Invalid path in forward rule — skipping: {exc}")
            continue

        if not exists(src):
            if not _resolve_missing_source(src, rule, upstreams=upstreams, repo_root=repo_root):
                continue

        # Record memory entry with clean relative paths
        mem_from = get_rel_path(raw_src, repo_root)
        mem_to = get_rel_path(raw_dst, repo_root)

        mem_entry = MemoryEntry(
            memory_id=generate_hash_id(),
            upstream_id=rule.upstream_id,
            forward_id=rule.forward_id,
            project_name=rule.project_name,
            from_path=mem_from,
            to_path=mem_to,
            last_synced=now_iso,
        )
        current_memory.append(mem_entry)

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
                # Submodule defense: check if dst was accidentally tracked as gitlink (160000)
                if repo_root:
                    rel_dst = get_rel_path(dst, repo_root)
                    ok_ls, out_ls = run_git(["ls-files", "-s", rel_dst], repo_root, logger)
                    if ok_ls and out_ls.startswith("160000"):
                        logger.warning(f"  🔧 Destination {rel_dst} is tracked as a git submodule (160000) — untracking submodule")
                        run_git(["rm", "--cached", rel_dst], repo_root, logger)

                shutil.copytree(
                    src, dst,
                    dirs_exist_ok=True,
                    copy_function=_incremental_copy_function,
                    ignore=_ignore_copy_patterns,
                )
                # Auto-prune mirror: prune non-matching files and .git
                _prune_extraneous(src, dst, repo_root=repo_root)
                logger.info(f"     ✅  [Dir]  {src} → {dst}")
                copied.append(name)

        except Exception as exc:
            logger.error(f"     ✗  {exc}")

    return copied, current_memory


def cleanup_orphans(
    previous: set[str] | list[MemoryEntry] | list[str],
    current: set[str] | list[ForwardRule] | list[MemoryEntry] | list[str] | None = None,
    repo_root: str = "",
    upstreams: list[UpstreamEntry] | None = None,
) -> list[str]:
    """
    Remove destination paths that are no longer part of the managed configuration.

    Supports:
      1. Structured mode: Uses MemoryEntry list to track lineage by forward_id
         and upstream_id, detecting deletions, renamed to_paths, or modified from_paths.
      2. Legacy string mode: (previous_paths - current_paths).

    Returns:
        removed: list of names that were cleaned up
    """
    removed: list[str] = []
    orphans: set[str] = set()

    # Determine mode based on previous parameter type
    is_structured = False
    if isinstance(previous, list) and len(previous) > 0 and isinstance(previous[0], MemoryEntry):
        is_structured = True

    if is_structured:
        # Structured Mode: Match by forward_id and upstream_id
        prev_entries: list[MemoryEntry] = previous  # type: ignore[assignment]
        curr_forwards: list[ForwardRule] = (
            [f for f in current if isinstance(f, ForwardRule)]  # type: ignore[union-attr]
            if current is not None else []
        )

        active_upstream_ids = (
            {u.upstream_id for u in upstreams if u.upstream_id}
            if upstreams is not None else None
        )
        active_forward_ids = {f.forward_id for f in curr_forwards if f.enabled and f.forward_id}
        active_forward_map = {f.forward_id: f for f in curr_forwards if f.enabled and f.forward_id}
        active_dsts = {get_rel_path(f.to_path, repo_root) for f in curr_forwards if f.enabled and f.to_path}

        for entry in prev_entries:
            if not entry.to_path:
                continue

            entry_to_norm = get_rel_path(entry.to_path, repo_root)
            entry_from_norm = get_rel_path(entry.from_path, repo_root)

            # 1. Upstream deleted -> cascade delete all its destinations
            if active_upstream_ids is not None and entry.upstream_id and entry.upstream_id not in active_upstream_ids:
                orphans.add(entry.to_path)
                continue

            # 2. Forward rule deleted or disabled
            if entry.forward_id and entry.forward_id not in active_forward_ids:
                if entry_to_norm not in active_dsts:
                    orphans.add(entry.to_path)
                continue

            # 3. Forward rule's to_path changed -> old to_path is orphaned
            if entry.forward_id and entry.forward_id in active_forward_map:
                curr_rule = active_forward_map[entry.forward_id]
                curr_to_norm = get_rel_path(curr_rule.to_path, repo_root)
                curr_from_norm = get_rel_path(curr_rule.from_path, repo_root)

                if curr_to_norm != entry_to_norm:
                    orphans.add(entry.to_path)
                    continue

                # 4. Forward rule's from_path changed -> purge destination before mirroring new source
                if curr_from_norm != entry_from_norm:
                    orphans.add(entry.to_path)
                    continue

    else:
        # Legacy Set / String Mode
        prev_set = {get_rel_path(p if isinstance(p, str) else getattr(p, "to_path", str(p)), repo_root) for p in previous}
        curr_set = set()
        if current is not None:
            curr_set = {get_rel_path(c if isinstance(c, str) else getattr(c, "to_path", str(c)), repo_root) for c in current}
        orphans = prev_set - curr_set

    # Perform cleanup for all detected orphan paths
    for orphan_rel in orphans:
        try:
            orphan_abs = (
                get_abs_path(repo_root, orphan_rel)
                if repo_root and not orphan_rel.startswith("/")
                else get_abs_path(orphan_rel)
            )
        except Exception as exc:
            logger.warning(f"  ⚠️  Invalid orphan path — skipping: {orphan_rel} ({exc})")
            continue

        if exists(orphan_abs):
            name = orphan_abs.rsplit("/", 1)[-1]
            logger.warning(f"  🗑️  Removing orphaned upstream skill: {name}")
            try:
                # Remove from git index first if repo_root is provided
                if repo_root:
                    rel_repo = get_rel_path(orphan_abs, repo_root)
                    run_git(["rm", "-r", "-f", "--cached", "--quiet", rel_repo], repo_root, logger)
                # Then remove from disk
                delete(orphan_abs)
                removed.append(name)
                logger.info(f"     ✅  Removed orphan: {name}")
            except Exception as exc:
                logger.error(f"     ✗  Failed to remove {orphan_rel}: {exc}")

    return removed
