"""
Smart commit and push service — per-upstream commits with template messages.
"""

from src.config import Settings, setup_logger, get_abs_path
from src.providers import run_git, repo_is_dirty
from src.schema import CommitMessages, ForwardRule, UpstreamEntry

logger = setup_logger(Settings.LOG_DIR / "service.log", name="gitmanager.services.commit")


def classify_changes(
    status_output: str,
    forwards: list[ForwardRule],
    upstreams: list[UpstreamEntry],
    repo_root: str,
) -> dict[str, list[str]]:
    """
    Classify git status changes into upstream-specific buckets.

    Only files matching an active forward rule destination are included.
    Unmatched files (user's own manual work) are intentionally SKIPPED —
    the sync job must never auto-commit content outside forward rules.

    Returns:
        upstream_changes: {upstream_name: [file_paths]}
    """
    upstream_changes: dict[str, list[str]] = {}
    skipped = 0

    for line in status_output.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) < 2:
            continue

        changed_file = parts[1].strip('"')
        if " -> " in changed_file:
            changed_file = changed_file.split(" -> ")[-1].strip('"')

        changed_abs = get_abs_path(changed_file)

        matched_upstream = _match_to_upstream(changed_abs, forwards, upstreams)

        if matched_upstream:
            upstream_changes.setdefault(matched_upstream, []).append(changed_file)
        else:
            skipped += 1

    if skipped:
        logger.debug(f"     Skipped {skipped} unmanaged file(s) — not in any forward rule")

    return upstream_changes


def _match_to_upstream(
    changed_abs: str,
    forwards: list[ForwardRule],
    upstreams: list[UpstreamEntry],
) -> str | None:
    """Match a changed file path to its upstream origin via forward rules."""
    for rule in forwards:
        if not rule.enabled or not rule.to_path:
            continue

        dst_abs = get_abs_path(rule.to_path)
        is_match = changed_abs == dst_abs or changed_abs.startswith(dst_abs + "/")

        if is_match and rule.from_path:
            src_abs = get_abs_path(rule.from_path)
            for up in upstreams:
                up_abs = get_abs_path(up.path)
                if src_abs == up_abs or src_abs.startswith(up_abs + "/"):
                    return up.name

    return None


def commit_and_push(
    repo_root: str,
    upstream_changes: dict[str, list[str]],
    branch: str,
    current_time: str,
    commit_messages: CommitMessages,
    auto_push: bool = True,
) -> bool:
    """
    Stage and commit per-upstream changes, then push.

    Only files matched to an upstream via forward rules are committed.
    User's own unmanaged files are never touched.

    Returns:
        True if push succeeded (or nothing to push).
    """
    if not upstream_changes:
        logger.info("  ✅  Nothing to commit — repo is clean.")
        return True

    # 1. Commit per upstream
    for up_name, files in upstream_changes.items():
        if not files:
            continue
        ok_add, out_add = run_git(["add", "--"] + files, repo_root, logger)
        if not ok_add:
            logger.error(f"     ✗  git add failed for {up_name}: {out_add}")

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
        ok_cmt, out_cmt = run_git(["commit", "-m", msg], repo_root, logger)
        if not ok_cmt:
            logger.error(f"     ✗  git commit failed for {up_name}: {out_cmt}")

    # 2. Check for any remaining unmanaged changes (log only, don't commit)
    ok, remaining = run_git(["status", "--porcelain"], repo_root, logger)
    if ok and remaining.strip():
        unmanaged = len(remaining.strip().splitlines())
        logger.debug(f"     ℹ️  {unmanaged} unmanaged file(s) left uncommitted (user's own)")

    if not auto_push:
        logger.info("  ⏭  Auto-push disabled — skipping push.")
        return True

    # 4. Push
    # NOTE: No pre-push pull here! Step 0 already runs git pull --rebase.
    # A second pull here would restore orphaned files from remote that were
    # just deleted by cleanup_orphans, causing the ghost skill zombie loop.
    logger.info(f"  🚀 Pushing → origin/{branch} …")
    ok, out = run_git(["push", "origin", branch], repo_root, logger)
    if not ok:
        # If push fails due to non-fast-forward, try pull + push once
        if "non-fast-forward" in out or "rejected" in out:
            logger.warning("     ⚠️  Push rejected — pulling and retrying…")
            ok_pull, _ = run_git(
                ["pull", "--rebase", "--autostash", "origin", branch],
                repo_root, logger,
            )
            if ok_pull:
                ok, out = run_git(["push", "origin", branch], repo_root, logger)

        if not ok:
            logger.error(f"     ✗  {out}")
            return False

    logger.info("     ✅  Push successful.")
    return True
