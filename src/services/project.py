"""
Project registry CRUD — manages projects.json and per-project config directories.
"""

import re
import threading
from datetime import datetime

from src.config import (
    Settings, setup_logger,
    read_json, write_json, exists, ensure_dir, delete,
)
from src.schema import (
    ProjectMeta, ProjectDetail, ProjectCreate, ProjectUpdate,
    UpstreamEntry, ForwardRule, GitConfig, ScheduleConfig, AutomationConfig,
)
from src.core.resolver import resolve_placeholders

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
    """Load full project config (meta + per-project data)."""
    projects = _load_registry()
    meta = next((p for p in projects if p.id == project_id), None)
    if not meta:
        return None

    # Read per-project configs
    raw_upstream = resolve_placeholders(
        _read_project_json(project_id, Settings.UPSTREAM_FILE),
        repo_root=meta.path,
    )
    raw_forward = resolve_placeholders(
        _read_project_json(project_id, Settings.FORWARD_FILE),
        repo_root=meta.path,
    )
    raw_automation = resolve_placeholders(
        _read_project_json(project_id, Settings.AUTOMATION_FILE),
        repo_root=meta.path,
    )

    upstreams = [UpstreamEntry(**u) for u in raw_upstream.get("upstreams", [])]
    forwards = [ForwardRule(**f) for f in raw_forward.get("forwards", [])]
    automation = AutomationConfig(**raw_automation)

    return ProjectDetail(
        **meta.model_dump(),
        upstreams=upstreams,
        forwards=forwards,
        git=automation.git,
        schedule=automation.schedule,
    )


def create_project(data: ProjectCreate) -> ProjectMeta:
    """Create a new project with default configs."""
    with _registry_lock:
        project_id = _slugify(data.name)
        now = datetime.now().isoformat()

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
            _write_project_json(project_id, Settings.UPSTREAM_FILE, {
                "upstreams": [u.model_dump() for u in data.upstreams]
            })

        # Update forward.json
        if data.forwards is not None:
            _write_project_json(project_id, Settings.FORWARD_FILE, {
                "forwards": [f.model_dump(by_alias=True) for f in data.forwards]
            })

        # Update automation.json
        if data.git is not None or data.schedule is not None:
            current = _read_project_json(project_id, Settings.AUTOMATION_FILE)
            if data.schedule is not None:
                current["schedule"] = data.schedule.model_dump()
            if data.git is not None:
                current["git"] = data.git.model_dump()
            _write_project_json(project_id, Settings.AUTOMATION_FILE, current)

        # Update registry timestamp
        meta.updated_at = datetime.now().isoformat()
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
