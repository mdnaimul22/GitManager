"""
Fan-in point. Orchestrates Core logic and Providers. This is the only layer where Core and Providers converge to fulfill application-specific use cases. Business logic stays in Core, while Services handle the high-level orchestration (Dont remove this Comments).
"""

from .sync import sync_job
from .upstream import pull_upstreams
from .forward import forward_skills, cleanup_orphans, load_registry, save_registry
from .commit import classify_changes, commit_and_push
from .project import (
    list_projects, get_project, create_project,
    update_project, delete_project, update_project_status,
)

__all__ = [
    "sync_job",
    "pull_upstreams",
    "forward_skills",
    "cleanup_orphans",
    "load_registry",
    "save_registry",
    "classify_changes",
    "commit_and_push",
    "list_projects",
    "get_project",
    "create_project",
    "update_project",
    "delete_project",
    "update_project_status",
]
