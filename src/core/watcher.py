"""
Watches per-project JSON config files for changes and provides hot-reload.
Parses raw JSON into typed Pydantic models from schema/.
"""

import json
import os
import sys

from src.config import Settings, read_text, exists, get_abs_path, setup_logger
from src.schema import UpstreamEntry, ForwardRule, AutomationConfig

from .resolver import resolve_placeholders

logger = setup_logger(Settings.LOG_DIR / "core.log", name="gitmanager.core.watcher")


class ConfigWatcher:
    """
    Tracks mtime of all per-project JSON config files.
    Call has_changed() to detect edits, then reload() to pull the new config.
    """

    def __init__(self, project_id: str, project_path: str) -> None:
        self.project_id = project_id
        self.project_path = project_path
        self._mtimes: dict[str, float] = {}

        # Typed config data
        self.upstreams: list[UpstreamEntry] = []
        self.forwards: list[ForwardRule] = []
        self.automation: AutomationConfig = AutomationConfig()

        self._do_load()

    # ── Internal helpers ───────────────────────────────────────────────────

    @property
    def _config_files(self) -> list[str]:
        """Filenames of per-project config files."""
        return [
            Settings.UPSTREAM_FILE,
            Settings.FORWARD_FILE,
            Settings.AUTOMATION_FILE,
        ]

    def _project_dir(self) -> str:
        """Relative path to this project's config directory."""
        return f"{Settings.RAW_DATA_DIR}/{self.project_id}"

    def _file_rel(self, filename: str) -> str:
        """Resolve a config filename to its relative path."""
        return f"{self._project_dir()}/{filename}"

    def _read_json(self, rel_path: str) -> dict:
        """Read and parse a JSON file."""
        if not exists(rel_path):
            logger.warning(f"Config not found: {rel_path} — using defaults")
            return {}
        content = read_text(rel_path)
        return json.loads(content) or {}

    def _snapshot_mtimes(self) -> None:
        for filename in self._config_files:
            rel = self._file_rel(filename)
            abs_path = get_abs_path(rel)
            self._mtimes[rel] = (
                os.path.getmtime(abs_path) if exists(rel) else 0.0
            )

    def _do_load(self) -> None:
        # Load and resolve upstream config
        raw_upstream = resolve_placeholders(
            self._read_json(self._file_rel(Settings.UPSTREAM_FILE)),
            repo_root=self.project_path,
        )
        self.upstreams = [
            UpstreamEntry(**entry)
            for entry in raw_upstream.get("upstreams", [])
        ]

        # Load and resolve forward config
        raw_forward = resolve_placeholders(
            self._read_json(self._file_rel(Settings.FORWARD_FILE)),
            repo_root=self.project_path,
        )
        self.forwards = [
            ForwardRule(**rule)
            for rule in raw_forward.get("forwards", [])
        ]

        # Load and resolve automation config
        raw_automation = resolve_placeholders(
            self._read_json(self._file_rel(Settings.AUTOMATION_FILE)),
            repo_root=self.project_path,
        )
        self.automation = AutomationConfig(**raw_automation)

        self._snapshot_mtimes()

    # ── Schedule helpers ───────────────────────────────────────────────────

    def sched_params(self) -> tuple[str | None, int]:
        """Return (run_at, interval_minutes) from automation config."""
        return (
            self.automation.schedule.run_at,
            self.automation.schedule.interval_minutes,
        )

    @property
    def poll_interval(self) -> int:
        """Seconds between hot-reload checks."""
        return self.automation.schedule.poll_interval_seconds

    # ── Public API ─────────────────────────────────────────────────────────

    def has_changed(self) -> bool:
        """True if any config file was modified since last load."""
        for filename in self._config_files:
            rel = self._file_rel(filename)
            abs_path = get_abs_path(rel)
            mtime = os.path.getmtime(abs_path) if exists(rel) else 0.0
            if self._mtimes.get(rel) != mtime:
                return True
        return False

    def reload(self) -> dict[str, dict]:
        """
        Reload all JSON files and return a dict describing what changed.
        Keys: 'upstreams', 'forwards', 'schedule'
        """
        old_sched = self.sched_params()
        old_upstream_count = len(self.upstreams)
        old_forward_count = len(self.forwards)

        self._do_load()

        new_sched = self.sched_params()
        new_upstream_count = len(self.upstreams)
        new_forward_count = len(self.forwards)

        changes: dict[str, dict] = {}

        if old_upstream_count != new_upstream_count:
            changes["upstreams"] = {"before": old_upstream_count, "after": new_upstream_count}

        if old_forward_count != new_forward_count:
            changes["forwards"] = {"before": old_forward_count, "after": new_forward_count}

        if old_sched != new_sched:
            changes["schedule"] = {"before": old_sched, "after": new_sched}

        return changes
