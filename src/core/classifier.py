"""
Change classification domain engine.

Pure business logic for:
- Parsing git status lines.
- Classifying modified paths into upstream-mapped buckets vs manual changes.
- Filtering staged deletions to avoid git add errors.
"""

from src.config import Settings, setup_logger, get_rel_path
from src.schema import ForwardRule, UpstreamEntry

logger = setup_logger(Settings.LOG_DIR / "core.log", name="gitmanager.core.classifier")


class ChangeClassifier:
    """
    Evaluates workspace status against configuration rules.
    Pure domain logic: decides which files belong to which upstream lineage.
    """

    def __init__(
        self,
        forwards: list[ForwardRule],
        upstreams: list[UpstreamEntry],
        repo_root: str = "",
    ) -> None:
        self.forwards = forwards
        self.upstreams = upstreams
        self.repo_root = repo_root

    def classify_status(
        self, status_output: str
    ) -> tuple[dict[str, list[str]], list[str]]:
        """
        Classify git status changes into upstream-specific buckets and manual changes.

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

            changed_rel = get_rel_path(changed_file, self.repo_root)
            matched_upstream = self._match_to_upstream(changed_rel)

            if matched_upstream:
                upstream_changes.setdefault(matched_upstream, []).append(changed_file)
            else:
                manual_changes.append(changed_file)

        if manual_changes:
            logger.debug(f"Found {len(manual_changes)} manual file(s) outside forward rules")

        return upstream_changes, manual_changes

    def _match_to_upstream(self, changed_rel: str) -> str | None:
        """Match a changed relative path to an upstream name via active forward rules."""
        up_id_map = {u.id: u.name for u in self.upstreams if u.id}
        up_name_set = {u.name for u in self.upstreams if u.name}

        for rule in self.forwards:
            if not rule.enabled or not rule.to_path:
                continue

            dst_rel = get_rel_path(rule.to_path, self.repo_root).rstrip("/")
            is_match = changed_rel == dst_rel or changed_rel.startswith(dst_rel + "/")

            if is_match:
                if rule.upstream_id and rule.upstream_id in up_id_map:
                    return up_id_map[rule.upstream_id]
                if rule.upstream and rule.upstream in up_name_set:
                    return rule.upstream
                if rule.from_path:
                    src_rel = get_rel_path(rule.from_path, self.repo_root).rstrip("/")
                    for up in self.upstreams:
                        up_rel = get_rel_path(up.path, self.repo_root).rstrip("/")
                        if src_rel == up_rel or src_rel.startswith(up_rel + "/"):
                            return up.name

        return None

    @staticmethod
    def filter_staged_deletions(files: list[str], status_output: str) -> list[str]:
        """
        Return only files that need to be staged with 'git add'.
        Files that are already staged as deleted ('D ') in Git index are skipped.
        """
        if not status_output:
            return files

        staged_deletions: set[str] = set()
        for line in status_output.splitlines():
            if len(line) < 3:
                continue
            code = line[:2]
            if code[0] == "D":
                p = line[2:].strip().strip('"')
                if " -> " in p:
                    p = p.split(" -> ")[-1].strip('"')
                staged_deletions.add(p)

        return [f for f in files if f not in staged_deletions]
