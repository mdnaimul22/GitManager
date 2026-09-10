"""
Orphan detection domain engine.

Pure business logic for:
- Detecting orphan destinations from memory snapshots vs current forwarding rules.
- Cascade deletion detection on upstream removals.
- Path mutation / rename tracking across forward rules.
"""

from src.config import Settings, setup_logger, get_rel_path
from src.schema import ForwardRule, MemoryEntry, UpstreamEntry

logger = setup_logger(Settings.LOG_DIR / "core.log", name="gitmanager.core.orphan")


class OrphanEngine:
    """
    Analyzes historical memory and current configuration to determine
    which destination paths are orphaned, renamed, or modified.
    """

    def __init__(self, repo_root: str = "") -> None:
        self.repo_root = repo_root

    def detect_orphans(
        self,
        previous: set[str] | list[MemoryEntry] | list[str],
        current: set[str] | list[ForwardRule] | list[MemoryEntry] | list[str] | None = None,
        upstreams: list[UpstreamEntry] | None = None,
    ) -> set[str]:
        """
        Detect destination paths that are no longer part of managed configuration.
        Supports structured lineage matching and legacy sets.
        """
        orphans: set[str] = set()

        is_structured = False
        if isinstance(previous, list) and len(previous) > 0 and isinstance(previous[0], MemoryEntry):
            is_structured = True

        if is_structured:
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
            active_dsts = {get_rel_path(f.to_path, self.repo_root) for f in curr_forwards if f.enabled and f.to_path}

            for entry in prev_entries:
                if not entry.to_path:
                    continue

                entry_to_norm = get_rel_path(entry.to_path, self.repo_root)
                entry_from_norm = get_rel_path(entry.from_path, self.repo_root)

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
                    curr_to_norm = get_rel_path(curr_rule.to_path, self.repo_root)
                    curr_from_norm = get_rel_path(curr_rule.from_path, self.repo_root)

                    if curr_to_norm != entry_to_norm:
                        orphans.add(entry.to_path)
                        continue

                    # 4. Forward rule's from_path changed -> purge destination before mirroring new source
                    if curr_from_norm != entry_from_norm:
                        orphans.add(entry.to_path)
                        continue
        else:
            # Legacy Set / String Mode
            prev_set = {
                get_rel_path(p if isinstance(p, str) else getattr(p, "to_path", str(p)), self.repo_root)
                for p in previous
            }
            curr_set = set()
            if current is not None:
                curr_set = {
                    get_rel_path(c if isinstance(c, str) else getattr(c, "to_path", str(c)), self.repo_root)
                    for c in current
                }
            orphans = prev_set - curr_set

        return orphans
