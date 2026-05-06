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
) -> tuple[dict[str, list[str]], list[str]]:
    """
    Classify git status changes into upstream-specific and manual buckets.

    Returns:
        upstream_changes: {upstream_name: [file_paths]}
        manual_changes: [file_paths]
    """
    upstream_changes: dict[str, list[str]] = {}
    manual_changes: list[str] = []

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
            manual_changes.append(changed_file)

    return upstream_changes, manual_changes


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
    manual_changes: list[str],
    branch: str,
    current_time: str,
    commit_messages: CommitMessages,
    auto_push: bool = True,
) -> bool:
    """
    Stage, commit per-upstream + manual changes, then push.

    Returns:
        True if push succeeded (or nothing to push).
    """
    if not repo_is_dirty(repo_root, logger):
        logger.info("  ✅  Nothing to commit — repo is clean.")
        return True

    # 1. Commit per upstream
    for up_name, files in upstream_changes.items():
        if not files:
            continue
        ok_add, out_add = run_git(["add", "--all", "--"] + files, repo_root, logger)
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

    # 2. Commit manual changes
    if manual_changes:
        ok_add, out_add = run_git(["add", "--all", "--"] + manual_changes, repo_root, logger)
        if not ok_add:
            logger.error(f"     ✗  git add failed for manual changes: {out_add}")

        msg = (
            commit_messages.manual
            .replace("{count}", str(len(manual_changes)))
            .replace("{datetime}", current_time)
        )

        logger.info(f"  📝 Committing {len(manual_changes)} manual changes …")
        ok_cmt, out_cmt = run_git(["commit", "-m", msg], repo_root, logger)
        if not ok_cmt:
            logger.error(f"     ✗  git commit failed for manual changes: {out_cmt}")

    # 3. Fail-fast check for missed files
    ok, remaining = run_git(["status", "--porcelain"], repo_root, logger)
    if ok and remaining.strip():
        logger.error("  ❌ FATAL (Fail-Fast): Uncommitted changes remain after sync!")
        for line in remaining.splitlines():
            logger.error(f"     Uncommitted: {line}")
        logger.error("     Aborting push to prevent dirty state.")
        return False

    if not auto_push:
        logger.info("  ⏭  Auto-push disabled — skipping push.")
        return True

    # 4. Push
    logger.info(f"  🚀 Pushing → origin/{branch} …")
    ok_pull, out_pull = run_git(
        ["pull", "--rebase", "--autostash", "origin", branch], repo_root, logger
    )
    if not ok_pull:
        logger.error(f"     ✗  Pre-push pull failed: {out_pull}")

    ok, out = run_git(["push", "origin", branch], repo_root, logger)
    if not ok:
        logger.error(f"     ✗  {out}")
        return False

    logger.info("     ✅  Push successful.")
    return True
