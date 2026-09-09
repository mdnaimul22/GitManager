"""
Smart commit and push service — per-upstream commits and manual commits with template messages.
"""

from src.config import Settings, setup_logger, get_rel_path
from src.providers import run_git, get_status
from src.schema import CommitMessages, ForwardRule, UpstreamEntry

logger = setup_logger(Settings.LOG_DIR / "service.log", name="gitmanager.services.commit")


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

        changed_rel = get_rel_path(changed_file, repo_root)

        matched_upstream = _match_to_upstream(changed_rel, forwards, upstreams, repo_root)

        if matched_upstream:
            upstream_changes.setdefault(matched_upstream, []).append(changed_file)
        else:
            manual_changes.append(changed_file)

    if manual_changes:
        logger.debug(f"     Found {len(manual_changes)} manual file(s) outside forward rules")

    return upstream_changes, manual_changes


def _match_to_upstream(
    changed_rel: str,
    forwards: list[ForwardRule],
    upstreams: list[UpstreamEntry],
    repo_root: str,
) -> str | None:
    """Match a changed file path to its upstream origin via forward rules."""
    up_id_map = {u.id: u.name for u in upstreams if u.id}
    up_name_set = {u.name for u in upstreams if u.name}

    for rule in forwards:
        if not rule.enabled or not rule.to_path:
            continue

        dst_rel = get_rel_path(rule.to_path, repo_root).rstrip("/")
        is_match = changed_rel == dst_rel or changed_rel.startswith(dst_rel + "/")

        if is_match:
            if rule.upstream_id and rule.upstream_id in up_id_map:
                return up_id_map[rule.upstream_id]
            if rule.upstream and rule.upstream in up_name_set:
                return rule.upstream
            if rule.from_path:
                src_rel = get_rel_path(rule.from_path, repo_root).rstrip("/")
                for up in upstreams:
                    up_rel = get_rel_path(up.path, repo_root).rstrip("/")
                    if src_rel == up_rel or src_rel.startswith(up_rel + "/"):
                        return up.name

    return None


def _filter_files_to_add(files: list[str], repo_root: str) -> list[str]:
    """
    Return only files that need to be staged with 'git add'.

    Files that are already staged as deleted ('D ') in Git's index are skipped,
    preventing 'fatal: pathspec did not match any files' error.
    """
    ok, status_out = get_status(repo_root, logger)
    if not ok or not status_out:
        return files

    staged_deletions: set[str] = set()
    for line in status_out.splitlines():
        if len(line) < 3:
            continue
        code = line[:2]
        if code[0] == "D":
            p = line[2:].strip().strip('"')
            if " -> " in p:
                p = p.split(" -> ")[-1].strip('"')
            staged_deletions.add(p)

    return [f for f in files if f not in staged_deletions]


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

        files_to_add = _filter_files_to_add(files, repo_root)
        if files_to_add:
            ok_add, out_add = run_git(["add", "--"] + files_to_add, repo_root, logger)
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
            if "nothing to commit" in out_cmt or "working tree clean" in out_cmt:
                logger.debug(f"     ⏭  Nothing to commit for {up_name}")
            else:
                logger.error(f"     ✗  git commit failed for {up_name}: {out_cmt}")

    # 2. Commit manual changes (user's own work)
    if manual_files:
        manual_to_add = _filter_files_to_add(manual_files, repo_root)
        if manual_to_add:
            ok_add, out_add = run_git(["add", "--"] + manual_to_add, repo_root, logger)
            if not ok_add:
                logger.error(f"     ✗  git add failed for manual changes: {out_add}")

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
            if "nothing to commit" in out_cmt or "working tree clean" in out_cmt:
                logger.debug("     ⏭  Nothing to commit for manual changes")
            else:
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
