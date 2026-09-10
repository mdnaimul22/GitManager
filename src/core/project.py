"""
Project configuration & registry domain engine.

Pure business logic for:
- Registry persistence & thread-safe synchronization.
- Slugification and unique identifier generation.
- Per-project config linking and schema normalization.
"""

import re
import threading
from src.config import (
    Settings, setup_logger,
    read_json, write_json, exists, ensure_dir, delete,
)
from src.helpers import time_now_iso
from src.schema import (
    ProjectMeta, ProjectDetail, ProjectCreate, ProjectUpdate,
    UpstreamEntry, ForwardRule, GitConfig, ScheduleConfig, AutomationConfig,
    generate_hash_id,
)

logger = setup_logger(Settings.LOG_DIR / "core.log", name="gitmanager.core.project")


class ProjectRegistry:
    """
    Core domain manager for projects registry and configuration files.
    Guarantees thread-safe atomic mutations.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

    @staticmethod
    def registry_path() -> str:
        return f"{Settings.RAW_DATA_DIR}/{Settings.PROJECTS_FILE}"

    @staticmethod
    def project_dir(project_id: str) -> str:
        return f"{Settings.RAW_DATA_DIR}/{project_id}"

    @staticmethod
    def slugify(text: str) -> str:
        text = text.lower().strip()
        text = re.sub(r'[^\w\s-]', '', text)
        text = re.sub(r'[\s_]+', '-', text)
        return text.strip('-') or "untitled"

    def read_project_json(self, project_id: str, filename: str) -> dict:
        rel = f"{self.project_dir(project_id)}/{filename}"
        if not exists(rel):
            return {}
        try:
            return read_json(rel)
        except Exception:
            return {}

    def write_project_json(self, project_id: str, filename: str, data: dict | list) -> None:
        rel = f"{self.project_dir(project_id)}/{filename}"
        parent = rel.rsplit("/", 1)[0]
        ensure_dir(parent)
        write_json(rel, data)

    def load_registry(self) -> list[ProjectMeta]:
        rel = self.registry_path()
        if not exists(rel):
            return []
        try:
            return [ProjectMeta(**p) for p in read_json(rel)]
        except Exception:
            return []

    def save_registry(self, projects: list[ProjectMeta]) -> None:
        rel = self.registry_path()
        parent = rel.rsplit("/", 1)[0]
        ensure_dir(parent)
        write_json(rel, [p.model_dump() for p in projects])

    def load_project_configs(
        self,
        project_id: str,
        project_path: str,
        resolve: bool = True,
    ) -> tuple[list[UpstreamEntry], list[ForwardRule], AutomationConfig]:
        """Load and normalize per-project configs linking upstream names and forward IDs."""
        raw_upstream = self.read_project_json(project_id, Settings.UPSTREAM_FILE)
        raw_forward = self.read_project_json(project_id, Settings.FORWARD_FILE)
        raw_automation = self.read_project_json(project_id, Settings.AUTOMATION_FILE)

        raw_upstreams = raw_upstream.get("upstreams", [])
        upstreams = [UpstreamEntry(**u) for u in raw_upstreams]

        up_by_name = {u.name: u.upstream_id for u in upstreams if u.name}
        up_by_path = {u.path.rstrip("/"): u.upstream_id for u in upstreams if u.path}
        up_by_id = {u.upstream_id: u.name for u in upstreams if u.upstream_id}

        raw_forwards = raw_forward.get("forwards", [])
        forwards: list[ForwardRule] = []
        for f in raw_forwards:
            rule = ForwardRule(**f)
            if not rule.upstream_id:
                if rule.project_name and rule.project_name in up_by_name:
                    rule.upstream_id = up_by_name[rule.project_name]
                elif rule.from_path:
                    src_clean = rule.from_path.rstrip("/")
                    for up_path, up_id in up_by_path.items():
                        if src_clean == up_path or src_clean.startswith(up_path + "/"):
                            rule.upstream_id = up_id
                            break
            if rule.upstream_id and rule.upstream_id in up_by_id:
                rule.project_name = up_by_id[rule.upstream_id]
            elif rule.upstream_id and rule.upstream_id not in up_by_id:
                rule.upstream_id = ""
                rule.project_name = ""
            forwards.append(rule)

        automation = AutomationConfig(**raw_automation)
        return upstreams, forwards, automation

    def create(self, data: ProjectCreate) -> ProjectMeta:
        with self._lock:
            project_id = self.slugify(data.name)
            now = time_now_iso()

            existing = self.load_registry()
            existing_ids = {p.id for p in existing}
            base_id = project_id
            counter = 1
            while project_id in existing_ids:
                project_id = f"{base_id}-{counter}"
                counter += 1

            meta = ProjectMeta(
                id=project_id,
                name=data.name,
                path=data.path,
                created_at=now,
                updated_at=now,
            )
            existing.append(meta)
            self.save_registry(existing)

        ensure_dir(self.project_dir(project_id))
        self.write_project_json(project_id, Settings.UPSTREAM_FILE, {"upstreams": []})
        self.write_project_json(project_id, Settings.FORWARD_FILE, {"forwards": []})
        self.write_project_json(project_id, Settings.AUTOMATION_FILE, {
            "schedule": ScheduleConfig().model_dump(),
            "git": GitConfig().model_dump(),
        })
        self.write_project_json(project_id, Settings.MEMORY_FILE, [])

        logger.info(f"Created project: {meta.name} ({project_id})")
        return meta

    def update(self, project_id: str, data: ProjectUpdate) -> ProjectDetail | None:
        with self._lock:
            projects = self.load_registry()
            meta = next((p for p in projects if p.id == project_id), None)
            if not meta:
                return None

            if data.upstreams is not None:
                up_id_name_map = {}
                for u in data.upstreams:
                    if not u.upstream_id:
                        u.upstream_id = generate_hash_id()
                    up_id_name_map[u.upstream_id] = u.project_name

                self.write_project_json(project_id, Settings.UPSTREAM_FILE, {
                    "upstreams": [u.model_dump() for u in data.upstreams]
                })

                if data.forwards is None:
                    existing_fwd_raw = self.read_project_json(project_id, Settings.FORWARD_FILE).get("forwards", [])
                    if existing_fwd_raw:
                        updated_any = False
                        synced_forwards = []
                        for raw_f in existing_fwd_raw:
                            f_rule = ForwardRule(**raw_f)
                            if f_rule.upstream_id:
                                if f_rule.upstream_id in up_id_name_map:
                                    if f_rule.project_name != up_id_name_map[f_rule.upstream_id]:
                                        f_rule.project_name = up_id_name_map[f_rule.upstream_id]
                                        updated_any = True
                                else:
                                    f_rule.upstream_id = ""
                                    f_rule.project_name = ""
                                    updated_any = True
                            synced_forwards.append(f_rule)
                        if updated_any:
                            self.write_project_json(project_id, Settings.FORWARD_FILE, {
                                "forwards": [f.model_dump(by_alias=True) for f in synced_forwards]
                            })

            if data.forwards is not None:
                current_up_map = {}
                if data.upstreams is not None:
                    current_up_map = {u.upstream_id: u.project_name for u in data.upstreams if u.upstream_id}
                else:
                    existing_ups = self.read_project_json(project_id, Settings.UPSTREAM_FILE).get("upstreams", [])
                    for u in existing_ups:
                        uid = u.get("upstream_id") or u.get("id")
                        uname = u.get("project_name") or u.get("name")
                        if uid and uname:
                            current_up_map[uid] = uname

                seen_ids = set()
                seen_rules = set()
                clean_forwards = []
                for f in data.forwards:
                    if not f.forward_id:
                        f.forward_id = generate_hash_id()

                    if f.forward_id in seen_ids:
                        continue
                    seen_ids.add(f.forward_id)

                    if f.upstream_id and f.upstream_id in current_up_map:
                        f.project_name = current_up_map[f.upstream_id]
                    elif f.upstream_id and f.upstream_id not in current_up_map:
                        f.upstream_id = ""
                        f.project_name = ""

                    if f.from_path and f.to_path:
                        key = (f.upstream_id, f.from_path, f.to_path)
                        if key in seen_rules:
                            continue
                        seen_rules.add(key)

                    clean_forwards.append(f)

                self.write_project_json(project_id, Settings.FORWARD_FILE, {
                    "forwards": [f.model_dump(by_alias=True) for f in clean_forwards]
                })

            if data.git is not None or data.schedule is not None or data.webhook is not None:
                current = self.read_project_json(project_id, Settings.AUTOMATION_FILE)
                if data.schedule is not None:
                    current["schedule"] = data.schedule.model_dump()
                if data.git is not None:
                    current["git"] = data.git.model_dump()
                if data.webhook is not None:
                    current["webhook"] = data.webhook.model_dump()
                self.write_project_json(project_id, Settings.AUTOMATION_FILE, current)

            meta.updated_at = time_now_iso()
            self.save_registry(projects)

            logger.info(f"Updated project: {project_id}")

        return self.get(project_id)

    def get(self, project_id: str) -> ProjectDetail | None:
        projects = self.load_registry()
        meta = next((p for p in projects if p.id == project_id), None)
        if not meta:
            return None

        upstreams, forwards, automation = self.load_project_configs(
            project_id, meta.path, resolve=False
        )

        return ProjectDetail(
            **meta.model_dump(),
            upstreams=upstreams,
            forwards=forwards,
            git=automation.git,
            schedule=automation.schedule,
            webhook=automation.webhook,
        )

    def delete(self, project_id: str) -> bool:
        with self._lock:
            projects = self.load_registry()
            filtered = [p for p in projects if p.id != project_id]
            if len(filtered) == len(projects):
                return False
            self.save_registry(filtered)

        d = self.project_dir(project_id)
        if exists(d):
            delete(d)

        logger.info(f"Deleted project: {project_id}")
        return True

    def update_status(self, project_id: str, status: str, last_sync: str | None = None) -> None:
        with self._lock:
            projects = self.load_registry()
            for p in projects:
                if p.id == project_id:
                    p.status = status  # type: ignore[assignment]
                    if last_sync:
                        p.last_sync = last_sync
                    break
            self.save_registry(projects)
