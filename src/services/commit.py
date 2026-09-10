"""
Smart commit and push orchestration service (Function Calling / Tool Facade).

Coordinates ChangeClassifier (Core) and run_git (Provider) to format
per-upstream commits and user manual changes.
"""

from src.config import Settings, setup_logger
from src.core import ChangeClassifier
from src.providers import run_git, get_status
from src.schema import CommitMessages, ForwardRule, UpstreamEntry

logger = setup_logger(Settings.LOG_DIR / "service.log", name="gitmanager.services.commit")


class CommitService:
    """
    Orchestration tool for staging, committing, and pushing git changes.
    """

    def __init__(self, repo_root: str) -> None:
        self.repo_root = repo_root

    def classify(
        self,
        status_output: str,
        forwards: list[ForwardRule],
        upstreams: list[UpstreamEntry],
    ) -> tuple[dict[str, list[str]], list[str]]:
        """Classify changes via ChangeClassifier core engine."""
        classifier = ChangeClassifier(forwards, upstreams, repo_root=self.repo_root)
        return classifier.classify_status(status_output)

    def commit_and_push(
        self,
        upstream_changes: dict[str, list[str]],
        branch: str,
        current_time: str,
        commit_messages: CommitMessages,
        auto_push: bool = True,
        manual_changes: list[str] | None = None,
    ) -> bool:
        """
        Stage and commit per-upstream changes and manual changes, then push.
        """
        manual_files = manual_changes or []
        has_upstream_changes = any(files for files in upstream_changes.values())
        has_manual_changes = bool(manual_files)

        if not has_upstream_changes and not has_manual_changes:
            logger.info("  ✅  Nothing to commit — repo is clean.")
            return True

        # 1. Commit per upstream
        for up_name, files in upstream_changes.items():
            if not files:
                continue

            ok_s, status_out = get_status(self.repo_root, logger)
            files_to_add = ChangeClassifier.filter_staged_deletions(files, status_out if ok_s else "")
            if files_to_add:
                ok_add, out_add = run_git(["add", "--"] + files_to_add, self.repo_root, logger)
                if not ok_add:
                    logger.error(f"     ✗  git add failed for {up_name}: {out_add}")
                    continue

            template = (
                commit_messages.upstreams.get(up_name)
                or commit_messages.upstreams.get("default", "sync: auto-update from {upstream_name} [{datetime}]")
            )
            msg = (
                template
                .replace("{upstream_name}", up_name)
                .replace("{count}", str(len(files)))
                .replace("{datetime}", current_time)
            )

            logger.info(f"  📝 Committing {len(files)} files for [{up_name}] …")
            ok_cmt, out_cmt = run_git(["commit", "-m", msg], self.repo_root, logger)
            if ok_cmt:
                logger.info(f"     ✅  Committed: {msg}")
            else:
                if "nothing to commit" in out_cmt:
                    logger.debug(f"     ℹ️  Nothing to commit for {up_name} (already clean)")
                else:
                    logger.warning(f"     ⚠️  Commit warning for {up_name}: {out_cmt}")

        # 2. Commit manual changes
        if manual_files:
            ok_s, status_out = get_status(self.repo_root, logger)
            manual_to_add = ChangeClassifier.filter_staged_deletions(manual_files, status_out if ok_s else "")
            if manual_to_add:
                ok_add, out_add = run_git(["add", "--"] + manual_to_add, self.repo_root, logger)
                if not ok_add:
                    logger.error(f"     ✗  git add failed for manual changes: {out_add}")
                    manual_files = []

            if manual_files:
                msg = (
                    commit_messages.manual
                    .replace("{count}", str(len(manual_files)))
                    .replace("{datetime}", current_time)
                )
                logger.info(f"  📝 Committing {len(manual_files)} manual files …")
                ok_cmt, out_cmt = run_git(["commit", "-m", msg], self.repo_root, logger)
                if ok_cmt:
                    logger.info(f"     ✅  Committed: {msg}")
                else:
                    if "nothing to commit" in out_cmt:
                        logger.debug("     ℹ️  Nothing to commit for manual changes")
                    else:
                        logger.warning(f"     ⚠️  Commit warning for manual changes: {out_cmt}")

        # 3. Push
        if not auto_push:
            logger.info("  ⏭  Auto-push disabled — skipping push")
            return True

        logger.info(f"  🚀 Pushing → origin/{branch} …")
        ok_push, out_push = run_git(["push", "origin", branch], self.repo_root, logger)
        if ok_push:
            logger.info("     ✅  Push successful.")
            return True
        else:
            logger.error(f"     ✗  Push failed: {out_push}")
            return False

