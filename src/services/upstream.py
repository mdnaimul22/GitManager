"""
Upstream repository pull/clone service.
"""

from src.config import Settings, setup_logger, exists, ensure_dir
from src.providers import run_git
from src.schema import UpstreamEntry

logger = setup_logger(Settings.LOG_DIR / "service.log", name="gitmanager.services.upstream")


def pull_upstreams(
    upstreams: list[UpstreamEntry],
) -> tuple[dict[str, bool], list[str]]:
    """
    Pull (or clone) all upstream repositories.

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

        if not exists(entry.path):
            if entry.url:
                logger.info(f"  ↓  Cloning [{entry.name}] from {entry.url} …")
                parent = entry.path.rsplit("/", 1)[0]
                ensure_dir(parent)
                ok, out = run_git(["clone", "-b", entry.branch, entry.url, entry.path], parent, logger)
                if ok:
                    logger.info("     ✅  Cloned successfully")
                    updated.append(entry.name)
                else:
                    logger.error(f"     ✗  Failed to clone: {out}")
                results[entry.name] = ok
                continue
            else:
                logger.warning(f"  ⚠️  [{entry.name}] path missing and no URL — skipping: {entry.path}")
                results[entry.name] = False
                continue

        logger.info(f"  ↓  Pulling [{entry.name}] branch '{entry.branch}' …")
        # Ensure we are fetching the specific branch and checking it out properly
        run_git(["fetch", "origin", entry.branch], entry.path, logger)
        ok, out = run_git(["reset", "--hard", f"origin/{entry.branch}"], entry.path, logger)

        if ok:
            logger.info(f"     ✅  Synced to origin/{entry.branch}")
            updated.append(entry.name)
        else:
            logger.error(f"     ✗  {out}")
        results[entry.name] = ok

    return results, updated
