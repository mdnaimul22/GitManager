"""
REST API endpoints for multi-project management.

Handlers are plain `def` (not async) because all service calls perform
blocking file I/O.  Uvicorn automatically runs plain `def` endpoints in
a threadpool, keeping the event loop unblocked.
"""

from fastapi import APIRouter, Depends, HTTPException

from src.schema import ProjectMeta, ProjectDetail, ProjectCreate, ProjectUpdate
from src.services import (
    list_projects, get_project, create_project,
    update_project, delete_project,
)
from src.core import WorkerPool
from .auth import require_auth

router = APIRouter(
    prefix="/api/projects",
    tags=["projects"],
    dependencies=[Depends(require_auth)],
)

# Shared worker pool — injected from main.py via app.state
_pool: WorkerPool | None = None


def set_pool(pool: WorkerPool) -> None:
    """Called from main.py to inject the shared worker pool."""
    global _pool
    _pool = pool


def _get_pool() -> WorkerPool:
    if _pool is None:
        raise HTTPException(status_code=503, detail="Worker pool not initialized")
    return _pool


# ── CRUD ───────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[ProjectMeta])
def api_list_projects():
    """List all projects with live status from worker pool."""
    projects = list_projects()
    pool = _get_pool()
    for p in projects:
        if pool.is_running(p.id):
            p.status = "running"
    return projects


@router.post("", response_model=ProjectMeta, status_code=201)
def api_create_project(data: ProjectCreate):
    """Create a new project."""
    return create_project(data)


@router.get("/{project_id}", response_model=ProjectDetail)
def api_get_project(project_id: str):
    """Get full project config."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    pool = _get_pool()
    if pool.is_running(project_id):
        project.status = "running"
    return project


@router.put("/{project_id}", response_model=ProjectDetail)
def api_update_project(project_id: str, data: ProjectUpdate):
    """Update project config (upstreams, forwards, git, schedule)."""
    result = update_project(project_id, data)
    if not result:
        raise HTTPException(status_code=404, detail="Project not found")
    return result


@router.delete("/{project_id}", status_code=204)
def api_delete_project(project_id: str):
    """Delete a project and stop its worker."""
    pool = _get_pool()
    pool.stop(project_id)
    if not delete_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")


# ── Worker Control ─────────────────────────────────────────────────────────────

@router.post("/{project_id}/run")
def api_run_project(project_id: str):
    """Start or trigger sync for a project."""
    projects = list_projects()
    meta = next((p for p in projects if p.id == project_id), None)
    if not meta:
        raise HTTPException(status_code=404, detail="Project not found")

    pool = _get_pool()
    if pool.is_running(project_id):
        return {"status": "already_running", "project_id": project_id}

    pool.start(meta)
    return {"status": "started", "project_id": project_id}


@router.post("/{project_id}/stop")
def api_stop_project(project_id: str):
    """Stop the background worker for a project."""
    pool = _get_pool()
    if not pool.stop(project_id):
        return {"status": "not_running", "project_id": project_id}
    return {"status": "stopped", "project_id": project_id}
