"""
Upstream planning and sparse-checkout domain engine.

Pure business logic for:
- Computing sparse checkout subpaths targeted by active forwarding rules.
- Planning clone options (blobless, sparse, branch targeting).
"""

from src.config import Settings, setup_logger, get_rel_path
from src.schema import ForwardRule, UpstreamEntry

logger = setup_logger(Settings.LOG_DIR / "core.log", name="gitmanager.core.upstream")


class UpstreamResolver:
    """
    Computes optimal checkout parameters and subpaths for upstream repositories.
    """

    @staticmethod
    def resolve_sparse_subpaths(
        entry: UpstreamEntry,
        forwards: list[ForwardRule] | None,
        repo_root: str = "",
    ) -> list[str]:
        """
        Extract relative subpaths in upstream targeted by active forward rules.
        """
        if not forwards:
            return []

        up_path = get_rel_path(entry.path, repo_root)
        subpaths: set[str] = set()

        for rule in forwards:
            if not rule.enabled or not rule.from_path:
                continue
            from_p = get_rel_path(rule.from_path, repo_root)
            if from_p == up_path:
                # Whole repository is forwarded
                return []

            rel_sub = ""
            if from_p.startswith(up_path + "/"):
                rel_sub = from_p[len(up_path):].strip("/")
            elif rule.upstream_id and entry.upstream_id and rule.upstream_id == entry.upstream_id:
                if from_p.startswith(up_path):
                    rel_sub = from_p[len(up_path):].strip("/")
                else:
                    rel_sub = from_p.strip("/")

            if rel_sub:
                subpaths.add(rel_sub)

        return sorted(list(subpaths))
