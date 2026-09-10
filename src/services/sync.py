"""
Sync orchestrator — high-level tool pipeline executing upstream sync.
"""

from src.config import Settings, setup_logger
from src.core import ConfigWatcher
from src.helpers import time_now_iso, time_now_formatted
from src.providers import run_git, get_status

from .upstream import UpstreamService
from .forward import ForwardService, load_memory, save_memory
from .commit import CommitService
from .project import ProjectService

logger = setup_logger(Settings.LOG_DIR / "service.log", name="gitmanager.services.sync")


class SyncService:
    """
    High-level orchestration tool for executing the full sync workflow.
    Invokable from CLI commands, background workers, or Webhook triggers.
    """

    def __init__(self, watcher: ConfigWatcher) -> None:
        self.watcher = watcher
        self.repo_root = watcher.project_path
        self.project_id = watcher.project_id
        self.git_cfg = watcher.automation.git
        self.branch = self.git_cfg.branch

        # Domain tool services
        self.upstream_service = UpstreamService(repo_root=self.repo_root)
        self.forward_service = ForwardService(repo_root=self.repo_root)
        self.commit_service = CommitService(repo_root=self.repo_root)

    def run(self) -> bool:
        """
        Execute the 4-step sync pipeline:
          0. Pull main repository
          1. Pull upstream repositories
          2. Clean orphaned or modified forward rules
          2.5. Forward skills with Auto-Prune Mirroring
          3. Classify, commit, and push
        """
        sep = "─" * 62
        now = time_now_formatted("%Y-%m-%d %H:%M:%S")

        logger.info(sep)
        logger.info(f"🔄  [{self.project_id}] SYNC STARTED  —  {now}")
        logger.info(sep)

        # Step 0 — Pull main repository
        logger.info(f"⬇️  [{self.project_id}] STEP 0 — Pulling main repository")
        ok, out = run_git(
            ["pull", "--rebase", "--autostash", "origin", self.branch],
            self.repo_root,
            logger,
        )
        if ok:
            logger.info(f"     ✅  Main repo updated: {out or 'Already up to date'}")
        else:
            logger.error(f"     ✗  Failed to pull main repo: {out}")
            logger.warning("        Push step may fail later due to this.")

        # Step 1 — Pull upstream repositories
        logger.info(f"📥 [{self.project_id}] STEP 1 — Pulling upstream repositories")
        pulls, updated_upstreams = self.upstream_service.pull(
            self.watcher.upstreams, forwards=self.watcher.forwards
        )

        # Step 2 — Orphan cleanup
        logger.info(f"🧹 [{self.project_id}] STEP 2 — Checking orphaned or modified upstream rules")
        memory_rel = f"{Settings.RAW_DATA_DIR}/{self.project_id}/{Settings.MEMORY_FILE}"
        previous_memory = load_memory(memory_rel)
        removed = self.forward_service.cleanup_orphans(
            previous=previous_memory,
            current=self.watcher.forwards,
            upstreams=self.watcher.upstreams,
        )

        # Step 2b — Commit orphan deletions immediately if any occurred
        if removed:
            orphan_time = time_now_formatted("%Y-%m-%d %H:%M")
            orphan_msg = f"chore: remove {len(removed)} orphaned skill(s) [{orphan_time}]"
            ok_cmt, _ = run_git(["commit", "-m", orphan_msg], self.repo_root, logger)
            if ok_cmt and self.git_cfg.auto_push:
                run_git(["push", "origin", self.branch], self.repo_root, logger)

        # Step 2.5 — Forward skill paths
        logger.info(f"📁 [{self.project_id}] STEP 2.5 — Forwarding skill paths (Auto-Prune Mirror)")
        copied, current_memory = self.forward_service.forward(
            self.watcher.forwards, upstreams=self.watcher.upstreams
        )

        # Step 3 — Commit & push
        logger.info(f"🚀 [{self.project_id}] STEP 3 — Committing & pushing to own repo")
        current_time = time_now_formatted("%Y-%m-%d %H:%M")

        ok, status_out = get_status(self.repo_root, logger)
        upstream_changes: dict[str, list[str]] = {}
        manual_changes: list[str] = []

        if ok and status_out.strip():
            upstream_changes, manual_changes = self.commit_service.classify(
                status_out, self.watcher.forwards, self.watcher.upstreams
            )

        push_ok = self.commit_service.commit_and_push(
            upstream_changes=upstream_changes,
            manual_changes=manual_changes,
            branch=self.branch,
            current_time=current_time,
            commit_messages=self.git_cfg.commit_messages,
            auto_push=self.git_cfg.auto_push,
        )

        # Step 4 — Update Memory snapshot
        if push_ok or copied or removed:
            save_memory(current_memory, memory_rel)

        # Update project status
        ProjectService().update_status(
            self.project_id,
            status="idle" if push_ok else "error",
            last_sync=time_now_iso(),
        )

        # Summary
        ok_cnt = sum(pulls.values())
        icon = "✅" if push_ok else "⚠️ "
        logger.info(sep)
        logger.info(
            f"{icon} [{self.project_id}] SYNC COMPLETE  |  "
            f"Upstreams: {ok_cnt}/{len(pulls)}  |  "
            f"Skills: +{len(copied)} / -{len(removed)}  |  "
            f"Push: {'OK' if push_ok else 'FAILED'}"
        )
        if copied:
            logger.info(f"   Added: {', '.join(copied)}")
        if removed:
            logger.info(f"   Removed: {', '.join(removed)}")
        logger.info(sep + "\n")

        return push_ok

