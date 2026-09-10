"""
Upstream repository pull/clone orchestration service (Function Calling / Tool Facade).

Coordinates UpstreamResolver (Core) and run_git (Provider) with:
- Blobless clone (--filter=blob:none) to drastically reduce bandwidth & disk usage.
- Sparse checkout (git sparse-checkout) to checkout only directories referenced in forward rules.
"""

from src.config import Settings, setup_logger, exists, ensure_dir, get_abs_path
from src.core import UpstreamResolver
from src.providers import run_git
from src.schema import UpstreamEntry, ForwardRule

logger = setup_logger(Settings.LOG_DIR / "service.log", name="gitmanager.services.upstream")


class UpstreamService:
    """
    Orchestration tool for syncing upstream Git repositories.
    Callable from CLI tools, background workers, or API endpoints.
    """

    def __init__(self, repo_root: str = "") -> None:
        self.repo_root = repo_root

    def pull(
        self,
        upstreams: list[UpstreamEntry],
        forwards: list[ForwardRule] | None = None,
    ) -> tuple[dict[str, bool], list[str]]:
        """
        Pull (or clone) all upstream repositories with blobless and sparse checkout optimizations.

        Returns:
            results: {name: success_bool}
            updated_upstreams: list of names that had actual changes
        """
        results: dict[str, bool] = {}
        updated: list[str] = []

        for entry in upstreams:
            if not entry.pull:
                logger.info(f"  ⏭  [{entry.name}] Pull disabled — skipping")
                results[entry.name] = True
                continue

            target_path = (
                get_abs_path(self.repo_root, entry.path)
                if self.repo_root and not entry.path.startswith("/")
                else get_abs_path(entry.path)
            )

            sparse_subpaths = (
                UpstreamResolver.resolve_sparse_subpaths(entry, forwards, repo_root=self.repo_root)
                if entry.sparse and forwards
                else []
            )

            if not exists(target_path):
                if not entry.url:
                    logger.warning(f"  ⚠️  [{entry.name}] path missing and no URL — skipping: {target_path}")
                    results[entry.name] = False
                    continue

                logger.info(f"  ↓  Cloning [{entry.name}] from {entry.url} …")
                parent = target_path.rsplit("/", 1)[0]
                ensure_dir(parent)

                if sparse_subpaths:
                    logger.info(f"     ⚡ Sparse checkout enabled: {', '.join(sparse_subpaths)}")
                    clone_cmd = ["clone", "-b", entry.branch]
                    if entry.blobless:
                        clone_cmd += ["--filter=blob:none"]
                    clone_cmd += ["--no-checkout", entry.url, target_path]

                    ok, out = run_git(clone_cmd, parent, logger)
                    if ok:
                        run_git(["sparse-checkout", "init", "--cone"], target_path, logger)
                        run_git(["sparse-checkout", "set", "--skip-checks"] + sparse_subpaths, target_path, logger)
                        ok_co, out_co = run_git(["checkout", entry.branch], target_path, logger)
                        if not ok_co:
                            logger.warning(f"     ⚠️  Sparse checkout fallback to regular checkout: {out_co}")
                            run_git(["checkout", entry.branch], target_path, logger)
                    else:
                        logger.warning(f"     ⚠️  Optimized clone failed ({out}), falling back to standard clone…")
                        ok, out = run_git(["clone", "-b", entry.branch, entry.url, target_path], parent, logger)
                else:
                    clone_cmd = ["clone", "-b", entry.branch]
                    if entry.blobless:
                        clone_cmd += ["--filter=blob:none"]
                    clone_cmd += [entry.url, target_path]

                    ok, out = run_git(clone_cmd, parent, logger)
                    if not ok and entry.blobless:
                        logger.warning(f"     ⚠️  Blobless clone failed ({out}), retrying standard clone…")
                        ok, out = run_git(["clone", "-b", entry.branch, entry.url, target_path], parent, logger)

                if ok:
                    logger.info("     ✅  Cloned successfully")
                    updated.append(entry.name)
                else:
                    logger.error(f"     ✗  Failed to clone: {out}")
                results[entry.name] = ok
                continue

            # Existing repository update
            logger.info(f"  ↓  Pulling [{entry.name}] branch '{entry.branch}' …")

            if sparse_subpaths:
                run_git(["sparse-checkout", "set", "--skip-checks"] + sparse_subpaths, target_path, logger)

            fetch_cmd = ["fetch", "origin", entry.branch]
            if entry.blobless:
                fetch_cmd += ["--filter=blob:none"]
            run_git(fetch_cmd, target_path, logger)

            ok, out = run_git(["reset", "--hard", f"origin/{entry.branch}"], target_path, logger)
            if ok:
                logger.info(f"     ✅  Synced to origin/{entry.branch}")
                updated.append(entry.name)
            else:
                logger.error(f"     ✗  {out}")
            results[entry.name] = ok

        return results, updated

