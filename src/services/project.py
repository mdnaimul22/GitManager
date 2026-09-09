"""
Project registry CRUD — manages projects.json and per-project config directories.
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


# ── Shared Config Loader ──────────────────────────────────────────────────────

def load_project_configs(
    project_id: str,
    project_path: str,
    resolve: bool = True,
) -> tuple[list[UpstreamEntry], list[ForwardRule], AutomationConfig]:
    """
    Load per-project config files directly with clean relative paths.
    """
    raw_upstream = _read_project_json(project_id, Settings.UPSTREAM_FILE)
    raw_forward = _read_project_json(project_id, Settings.FORWARD_FILE)
    raw_automation = _read_project_json(project_id, Settings.AUTOMATION_FILE)

    raw_upstreams = raw_upstream.get("upstreams", [])
    upstreams = [UpstreamEntry(**u) for u in raw_upstreams]

    # Map upstream IDs, names, and paths to link legacy forwards without upstream_id
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


logger = setup_logger(Settings.LOG_DIR / "service.log", name="gitmanager.services.project")

# Thread-safe guard for projects.json read-modify-write cycles.
# Workers (threads) and API handlers may mutate the registry concurrently.
_registry_lock = threading.Lock()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _registry_path() -> str:
    """Relative path to the global projects registry."""
    return f"{Settings.RAW_DATA_DIR}/{Settings.PROJECTS_FILE}"


def _project_dir(project_id: str) -> str:
    """Relative path to a project's config directory."""
    return f"{Settings.RAW_DATA_DIR}/{project_id}"


def _slugify(text: str) -> str:
    """Convert text to a URL/directory-safe slug."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    return text.strip('-') or "untitled"


def _read_project_json(project_id: str, filename: str) -> dict:
    """Read a per-project JSON config file."""
    rel = f"{_project_dir(project_id)}/{filename}"
    if not exists(rel):
        return {}
    try:
        return read_json(rel)
    except Exception:
        return {}


def _write_project_json(project_id: str, filename: str, data: dict | list) -> None:
    """Write a per-project JSON config file."""
    rel = f"{_project_dir(project_id)}/{filename}"
    parent = rel.rsplit("/", 1)[0]
    ensure_dir(parent)
    write_json(rel, data)


# ── Registry CRUD ─────────────────────────────────────────────────────────────

def _load_registry() -> list[ProjectMeta]:
    """Load all project metadata from registry."""
    rel = _registry_path()
    if not exists(rel):
        return []
    try:
        return [ProjectMeta(**p) for p in read_json(rel)]
    except Exception:
        return []


def _save_registry(projects: list[ProjectMeta]) -> None:
    """Save all project metadata to registry."""
    rel = _registry_path()
    parent = rel.rsplit("/", 1)[0]
    ensure_dir(parent)
    write_json(rel, [p.model_dump() for p in projects])


def list_projects() -> list[ProjectMeta]:
    """List all projects."""
    return _load_registry()


def get_project(project_id: str) -> ProjectDetail | None:
    """Load full project config (meta + per-project data) for API/UI."""
    projects = _load_registry()
    meta = next((p for p in projects if p.id == project_id), None)
    if not meta:
        return None

    upstreams, forwards, automation = load_project_configs(
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



def create_project(data: ProjectCreate) -> ProjectMeta:
    """Create a new project with default configs."""
    with _registry_lock:
        project_id = _slugify(data.name)
        now = time_now_iso()

        # Ensure unique ID
        existing = _load_registry()
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

        # Save to registry
        existing.append(meta)
        _save_registry(existing)

    # Create per-project config directory with defaults (outside lock — no registry contention)
    ensure_dir(_project_dir(project_id))
    _write_project_json(project_id, Settings.UPSTREAM_FILE, {"upstreams": []})
    _write_project_json(project_id, Settings.FORWARD_FILE, {"forwards": []})
    _write_project_json(project_id, Settings.AUTOMATION_FILE, {
        "schedule": ScheduleConfig().model_dump(),
        "git": GitConfig().model_dump(),
    })
    _write_project_json(project_id, Settings.MEMORY_FILE, [])

    logger.info(f"Created project: {meta.name} ({project_id})")
    return meta


def update_project(project_id: str, data: ProjectUpdate) -> ProjectDetail | None:
    """Update a project's config files."""
    with _registry_lock:
        projects = _load_registry()
        meta = next((p for p in projects if p.id == project_id), None)
        if not meta:
            return None

        # Update upstream.json
        if data.upstreams is not None:
            up_id_name_map = {}
            for u in data.upstreams:
                if not u.upstream_id:
                    u.upstream_id = generate_hash_id()
                up_id_name_map[u.upstream_id] = u.project_name

            _write_project_json(project_id, Settings.UPSTREAM_FILE, {
                "upstreams": [u.model_dump() for u in data.upstreams]
            })

            # If forwards was not included in this update, ensure existing forward.json
            # is updated if any upstream was renamed or deleted
            if data.forwards is None:
                existing_fwd_raw = _read_project_json(project_id, Settings.FORWARD_FILE).get("forwards", [])
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
                        _write_project_json(project_id, Settings.FORWARD_FILE, {
                            "forwards": [f.model_dump(by_alias=True) for f in synced_forwards]
                        })

        # Update forward.json with deduplication
        if data.forwards is not None:
            # Map upstream_id to current project_name if upstreams were provided
            current_up_map = {}
            if data.upstreams is not None:
                current_up_map = {u.upstream_id: u.project_name for u in data.upstreams if u.upstream_id}
            else:
                existing_ups = _read_project_json(project_id, Settings.UPSTREAM_FILE).get("upstreams", [])
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

                # Deduplicate identical rules (only when paths are specified)
                if f.from_path and f.to_path:
                    key = (f.upstream_id, f.from_path, f.to_path)
                    if key in seen_rules:
                        continue
                    seen_rules.add(key)

                clean_forwards.append(f)

            _write_project_json(project_id, Settings.FORWARD_FILE, {
                "forwards": [f.model_dump(by_alias=True) for f in clean_forwards]
            })

        # Update automation.json
        if data.git is not None or data.schedule is not None or data.webhook is not None:
            current = _read_project_json(project_id, Settings.AUTOMATION_FILE)
            if data.schedule is not None:
                current["schedule"] = data.schedule.model_dump()
            if data.git is not None:
                current["git"] = data.git.model_dump()
            if data.webhook is not None:
                current["webhook"] = data.webhook.model_dump()
            _write_project_json(project_id, Settings.AUTOMATION_FILE, current)

        # Update registry timestamp
        meta.updated_at = time_now_iso()
        _save_registry(projects)

        logger.info(f"Updated project: {project_id}")
        return get_project(project_id)


def delete_project(project_id: str) -> bool:
    """Delete a project from registry and remove its config directory."""
    with _registry_lock:
        projects = _load_registry()
        filtered = [p for p in projects if p.id != project_id]
        if len(filtered) == len(projects):
            return False
        _save_registry(filtered)

    # Remove per-project directory (outside lock — disk I/O)
    d = _project_dir(project_id)
    if exists(d):
        delete(d)

    logger.info(f"Deleted project: {project_id}")
    return True


def update_project_status(project_id: str, status: str, last_sync: str | None = None) -> None:
    """Update a project's status in the registry (called from worker threads)."""
    with _registry_lock:
        projects = _load_registry()
        for p in projects:
            if p.id == project_id:
                p.status = status  # type: ignore[assignment]
                if last_sync:
                    p.last_sync = last_sync
                break
        _save_registry(projects)
