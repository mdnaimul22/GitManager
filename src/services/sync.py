"""
Sync orchestrator — coordinates the full upstream sync pipeline.
"""

from src.config import Settings, setup_logger
from src.core import ConfigWatcher
from src.helpers import time_now_iso, time_now_formatted
from src.providers import run_git, get_status

from .upstream import pull_upstreams
from .forward import forward_skills, cleanup_orphans, load_memory, save_memory
from .commit import classify_changes, commit_and_push

logger = setup_logger(Settings.LOG_DIR / "service.log", name="gitmanager.services.sync")


def sync_job(watcher: ConfigWatcher) -> None:
    """
    Execute the full sync pipeline for a single project:
      0. Pull main repo
      1. Pull upstreams
      2. Orphan cleanup (lineage tracking by forward_id/upstream_id)
      2.5. Forward skills with Auto-Prune Mirroring
      3. Commit & push
    """
    sep = "─" * 62
    now = time_now_formatted("%Y-%m-%d %H:%M:%S")
    git_cfg = watcher.automation.git
    branch = git_cfg.branch
    repo_root = watcher.project_path
    project_id = watcher.project_id

    logger.info(sep)
    logger.info(f"🔄  [{project_id}] SYNC STARTED  —  {now}")
    logger.info(sep)

    # Step 0 — Pull main repository
    logger.info(f"⬇️  [{project_id}] STEP 0 — Pulling main repository")
    ok, out = run_git(
        ["pull", "--rebase", "--autostash", "origin", branch], repo_root, logger
    )
    if ok:
        logger.info(f"     ✅  Main repo updated: {out or 'Already up to date'}")
    else:
        logger.error(f"     ✗  Failed to pull main repo: {out}")
        logger.warning("        Push step may fail later due to this.")

    # Step 1 — Pull upstream repositories
    logger.info(f"📥 [{project_id}] STEP 1 — Pulling upstream repositories")
    pulls, updated_upstreams = pull_upstreams(watcher.upstreams, repo_root=repo_root, forwards=watcher.forwards)

    # Step 2 — Orphan cleanup (using structured memory with forward_id & upstream_id)
    logger.info(f"🧹 [{project_id}] STEP 2 — Checking orphaned or modified upstream rules")
    memory_rel = f"{Settings.RAW_DATA_DIR}/{project_id}/{Settings.MEMORY_FILE}"
    previous_memory = load_memory(memory_rel)
    removed = cleanup_orphans(
        previous=previous_memory,
        current=watcher.forwards,
        repo_root=repo_root,
        upstreams=watcher.upstreams,
    )

    # Step 2b — Commit orphan deletions immediately (before forwarding new files)
    # This ensures old wrong paths and submodules are purged from Git and remote first.
    if removed:
        orphan_time = time_now_formatted("%Y-%m-%d %H:%M")
        orphan_msg = f"chore: remove {len(removed)} orphaned skill(s) [{orphan_time}]"
        ok_cmt, _ = run_git(["commit", "-m", orphan_msg], repo_root, logger)
        if ok_cmt and git_cfg.auto_push:
            run_git(["push", "origin", branch], repo_root, logger)

    # Step 2.5 — Forward skill paths with Auto-Prune Mirror
    logger.info(f"📁 [{project_id}] STEP 2.5 — Forwarding skill paths (Auto-Prune Mirror)")
    copied, current_memory = forward_skills(watcher.forwards, repo_root=repo_root, upstreams=watcher.upstreams)

    # Step 3 — Commit & push
    logger.info(f"🚀 [{project_id}] STEP 3 — Committing & pushing to own repo")
    current_time = time_now_formatted("%Y-%m-%d %H:%M")

    ok, status_out = get_status(repo_root, logger)

    upstream_changes: dict[str, list[str]] = {}
    manual_changes: list[str] = []

    if ok and status_out.strip():
        upstream_changes, manual_changes = classify_changes(
            status_out, watcher.forwards, watcher.upstreams, repo_root
        )

    push_ok = commit_and_push(
        repo_root=repo_root,
        upstream_changes=upstream_changes,
        manual_changes=manual_changes,
        branch=branch,
        current_time=current_time,
        commit_messages=git_cfg.commit_messages,
        auto_push=git_cfg.auto_push,
    )

    # Step 4 — Update Memory (ONLY after sync and commit cycle completes)
    # Keeping previous memory intact until now ensures the evidence of old paths
    # is never lost prematurely if any step fails.
    if push_ok or copied or removed:
        save_memory(current_memory, memory_rel)

    # Update project status
    from .project import update_project_status
    update_project_status(
        project_id,
        status="idle" if push_ok else "error",
        last_sync=time_now_iso(),
    )

    # Summary
    ok_cnt = sum(pulls.values())
    icon = "✅" if push_ok else "⚠️️ "
    logger.info(sep)
    logger.info(
        f"{icon} [{project_id}] SYNC COMPLETE  |  "
        f"Upstreams: {ok_cnt}/{len(pulls)}  |  "
        f"Skills: +{len(copied)} / -{len(removed)}  |  "
        f"Push: {'OK' if push_ok else 'FAILED'}"
    )
    if copied:
        logger.info(f"   Added: {', '.join(copied)}")
    if removed:
        logger.info(f"   Removed: {', '.join(removed)}")
    logger.info(sep + "\n")
