"""
Smart commit and push service — per-upstream commits and manual commits with template messages.
"""

from src.config import Settings, setup_logger
from src.providers import run_git
from src.schema import CommitMessages, ForwardRule, UpstreamEntry

logger = setup_logger(Settings.LOG_DIR / "service.log", name="gitmanager.services.commit")


def _to_abs(path: str, repo_root: str) -> str:
    """Ensure path is resolved to absolute string against repo_root."""
    if not path:
        return ""
    if path.startswith("/"):
        return path
    return f"{repo_root.rstrip('/')}/{path.lstrip('/')}"


def classify_changes(
    status_output: str,
    forwards: list[ForwardRule],
    upstreams: list[UpstreamEntry],
    repo_root: str,
) -> tuple[dict[str, list[str]], list[str]]:
    """
    Classify git status changes into upstream-specific buckets and manual changes.

    Files matching an active forward rule destination are mapped to their upstream origin.
    All other changed files (user's own manual work) are gathered into manual_changes.

    Returns:
        (upstream_changes, manual_changes)
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

        changed_abs = _to_abs(changed_file, repo_root)

        matched_upstream = _match_to_upstream(changed_abs, forwards, upstreams, repo_root)

        if matched_upstream:
            upstream_changes.setdefault(matched_upstream, []).append(changed_file)
        else:
            manual_changes.append(changed_file)

    if manual_changes:
        logger.debug(f"     Found {len(manual_changes)} manual file(s) outside forward rules")

    return upstream_changes, manual_changes


def _match_to_upstream(
    changed_abs: str,
    forwards: list[ForwardRule],
    upstreams: list[UpstreamEntry],
    repo_root: str,
) -> str | None:
    """Match a changed file path to its upstream origin via forward rules."""
    for rule in forwards:
        if not rule.enabled or not rule.to_path:
            continue

        dst_abs = _to_abs(rule.to_path, repo_root).rstrip("/")
        is_match = changed_abs == dst_abs or changed_abs.startswith(dst_abs + "/")

        if is_match and rule.from_path:
            src_abs = _to_abs(rule.from_path, repo_root).rstrip("/")
            for up in upstreams:
                up_abs = _to_abs(up.path, repo_root).rstrip("/")
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
    manual_changes: list[str] | None = None,
) -> bool:
    """
    Stage and commit per-upstream changes and manual changes, then push.

    Returns:
        True if push succeeded (or nothing to push).
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
        ok_add, out_add = run_git(["add", "--"] + files, repo_root, logger)
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
        ok_cmt, out_cmt = run_git(["commit", "-m", msg], repo_root, logger)
        if not ok_cmt:
            logger.error(f"     ✗  git commit failed for {up_name}: {out_cmt}")

    # 2. Commit manual changes (user's own work)
    if manual_files:
        ok_add, out_add = run_git(["add", "--"] + manual_files, repo_root, logger)
        if not ok_add:
            logger.error(f"     ✗  git add failed for manual changes: {out_add}")
        else:
            template = (
                commit_messages.manual
                or "chore: manual update of {count} file(s) [{datetime}]"
            )
            msg = (
                template
                .replace("{count}", str(len(manual_files)))
                .replace("{datetime}", current_time)
            )
            logger.info(f"  📝 Committing {len(manual_files)} manual file(s) …")
            ok_cmt, out_cmt = run_git(["commit", "-m", msg], repo_root, logger)
            if not ok_cmt:
                logger.error(f"     ✗  git commit failed for manual changes: {out_cmt}")

    if not auto_push:
        logger.info("  ⏭  Auto-push disabled — skipping push.")
        return True

    # 3. Push
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
