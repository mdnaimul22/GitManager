"""
Path forwarding and orphan management orchestration service (Function Calling / Tool Facade).

Coordinates ForwardEngine, OrphanEngine (Core), and run_git (Provider).
"""

import shutil
from src.config import (
    Settings, setup_logger, get_abs_path, get_rel_path,
    read_json, write_json, exists, is_file, is_dir, ensure_dir, delete,
)
from src.core import ForwardEngine, OrphanEngine
from src.providers import run_git
from src.schema import ForwardRule, MemoryEntry, UpstreamEntry

logger = setup_logger(Settings.LOG_DIR / "service.log", name="gitmanager.services.forward")


# ── Structured Memory Persistence Helpers ─────────────────────────────────────

def load_memory(rel: str) -> list[MemoryEntry]:
    """Load managed skill memory entries from JSON."""
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



class ForwardService:
    """
    Orchestration tool for skill path forwarding, mirroring, and orphan cleanup.
    """

    def __init__(self, repo_root: str = "") -> None:
        self.repo_root = repo_root
        self.forward_engine = ForwardEngine(repo_root=repo_root)
        self.orphan_engine = OrphanEngine(repo_root=repo_root)

    def resolve_missing_source(
        self,
        src: str,
        rule: ForwardRule,
        upstreams: list[UpstreamEntry] | None = None,
    ) -> bool:
        """
        Verify and dynamically checkout missing source path if it exists in upstream Git repo.
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
                        get_abs_path(self.repo_root, u.path)
                        if self.repo_root and not u.path.startswith("/")
                        else get_abs_path(u.path)
                    )
                    if src == up_abs or src.startswith(up_abs + "/"):
                        matched_upstream = u
                        break

        if not matched_upstream:
            logger.warning(f"  ⚠️  Source missing — skipping: {src}")
            return False

        up_abs = (
            get_abs_path(self.repo_root, matched_upstream.path)
            if self.repo_root and not matched_upstream.path.startswith("/")
            else get_abs_path(matched_upstream.path)
        )

        if not exists(up_abs):
            logger.warning(f"  ⚠️  Upstream repository path missing: {up_abs}")
            return False

        rel_in_upstream = get_rel_path(src, up_abs)

        ok_head, _ = run_git(["cat-file", "-e", f"HEAD:{rel_in_upstream}"], up_abs, logger)
        if not ok_head and matched_upstream.url and matched_upstream.branch:
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

        if matched_upstream.sparse:
            run_git(["sparse-checkout", "add", "--skip-checks", rel_in_upstream], up_abs, logger)
        else:
            run_git(["checkout", "HEAD", "--", rel_in_upstream], up_abs, logger)

        if exists(src):
            logger.info(f"  📥 Dynamically checked out missing upstream path: {rel_in_upstream}")
            return True

        logger.warning(f"  ⚠️  Source missing — skipping: {src}")
        return False

    def forward(
        self,
        forwards: list[ForwardRule],
        upstreams: list[UpstreamEntry] | None = None,
    ) -> tuple[list[str], list[MemoryEntry]]:
        """
        Execute path forwarding rules with auto-pruning.
        """
        copied: list[str] = []
        current_memory: list[MemoryEntry] = []

        for rule in forwards:
            if not rule.enabled:
                continue

            raw_src = rule.from_path
            raw_dst = rule.to_path
            name = raw_src.rsplit("/", 1)[-1]

            try:
                src = (
                    get_abs_path(self.repo_root, raw_src)
                    if self.repo_root and not raw_src.startswith("/")
                    else get_abs_path(raw_src)
                )
                dst = (
                    get_abs_path(self.repo_root, raw_dst)
                    if self.repo_root and not raw_dst.startswith("/")
                    else get_abs_path(raw_dst)
                )
            except Exception as exc:
                logger.warning(f"  ⚠️  Invalid path in forward rule — skipping: {exc}")
                continue

            if not exists(src):
                if not self.resolve_missing_source(src, rule, upstreams=upstreams):
                    continue

            mem_entry = self.forward_engine.create_memory_entry(rule)
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

                    if self.forward_engine.should_copy(src, actual_dst):
                        shutil.copy2(get_abs_path(src), get_abs_path(actual_dst))
                        logger.info(f"     ✅  [File] {src} → {actual_dst}")
                        copied.append(name)
                    else:
                        logger.debug(f"     ⏭  [File] {name} — unchanged, skipped")

                elif is_dir(src):
                    ensure_dir(dst)
                    # Submodule defense
                    if self.repo_root:
                        rel_dst = get_rel_path(dst, self.repo_root)
                        ok_ls, out_ls = run_git(["ls-files", "-s", rel_dst], self.repo_root, logger)
                        if ok_ls and out_ls.startswith("160000"):
                            logger.warning(f"  🔧 Destination {rel_dst} is tracked as a git submodule — untracking")
                            run_git(["rm", "--cached", rel_dst], self.repo_root, logger)

                    shutil.copytree(
                        src, dst,
                        dirs_exist_ok=True,
                        copy_function=self.forward_engine.incremental_copy,
                        ignore=self.forward_engine.ignore_copy_patterns,
                    )
                    pruned = self.forward_engine.prune_extraneous(src, dst)
                    if self.repo_root and pruned:
                        for p in pruned:
                            run_git(["rm", "-r", "-f", "--cached", "--quiet", p], self.repo_root, logger)

                    logger.info(f"     ✅  [Dir]  {src} → {dst}")
                    copied.append(name)

            except Exception as exc:
                logger.error(f"     ✗  {exc}")

        return copied, current_memory

    def cleanup_orphans(
        self,
        previous: set[str] | list[MemoryEntry] | list[str],
        current: set[str] | list[ForwardRule] | list[MemoryEntry] | list[str] | None = None,
        upstreams: list[UpstreamEntry] | None = None,
    ) -> list[str]:
        """
        Orchestrate orphan cleanup: identify orphaned paths via OrphanEngine,
        remove from git index, and delete from disk.
        """
        removed: list[str] = []
        orphans = self.orphan_engine.detect_orphans(previous, current=current, upstreams=upstreams)

        for orphan_rel in orphans:
            try:
                orphan_abs = (
                    get_abs_path(self.repo_root, orphan_rel)
                    if self.repo_root and not orphan_rel.startswith("/")
                    else get_abs_path(orphan_rel)
                )
            except Exception as exc:
                logger.warning(f"  ⚠️  Invalid orphan path — skipping: {orphan_rel} ({exc})")
                continue

            name = orphan_rel.rstrip("/").rsplit("/", 1)[-1]
            logger.warning(f"  🗑️  Removing orphaned upstream skill: {name}")
            removed_any = False
            try:
                if self.repo_root:
                    rel_repo = get_rel_path(orphan_rel, self.repo_root) if orphan_rel.startswith("/") else orphan_rel.lstrip("/")
                    ok_rm, _ = run_git(["rm", "-r", "-f", "--cached", "--quiet", rel_repo], self.repo_root, logger)
                    if ok_rm:
                        removed_any = True

                if exists(orphan_abs):
                    delete(orphan_abs)
                    removed_any = True

                if removed_any:
                    removed.append(name)
                    logger.info(f"     ✅  Removed orphan: {name}")
            except Exception as exc:
                logger.error(f"     ✗  Failed to remove {orphan_rel}: {exc}")

        return removed
