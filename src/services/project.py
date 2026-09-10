"""
Project registry CRUD orchestration service (Function Calling / Tool Facade).

Coordinates ProjectRegistry (Core) to expose clean project operations for API and CLI.
"""

from src.config import Settings, setup_logger
from src.core import ProjectRegistry
from src.schema import (
    ProjectMeta, ProjectDetail, ProjectCreate, ProjectUpdate,
    UpstreamEntry, ForwardRule, AutomationConfig,
)

logger = setup_logger(Settings.LOG_DIR / "service.log", name="gitmanager.services.project")

# Shared singleton registry instance for application services
_registry = ProjectRegistry()


class ProjectService:
    """
    Orchestration tool for multi-project management.
    """

    def __init__(self, registry: ProjectRegistry | None = None) -> None:
        self.registry = registry or _registry

    def list_all(self) -> list[ProjectMeta]:
        return self.registry.load_registry()

    def get_meta(self, project_id: str) -> ProjectMeta | None:
        projects = self.list_all()
        return next((p for p in projects if p.id == project_id), None)

    def list_with_live_status(self, running_ids: set[str]) -> list[ProjectMeta]:
        projects = self.list_all()
        for p in projects:
            if p.id in running_ids:
                p.status = "running"
        return projects

    def get(self, project_id: str) -> ProjectDetail | None:
        return self.registry.get(project_id)

    def get_with_live_status(self, project_id: str, is_running: bool) -> ProjectDetail | None:
        project = self.get(project_id)
        if project and is_running:
            project.status = "running"
        return project

    def create(self, data: ProjectCreate) -> ProjectMeta:
        return self.registry.create(data)

    def update(self, project_id: str, data: ProjectUpdate) -> ProjectDetail | None:
        return self.registry.update(project_id, data)

    def delete(self, project_id: str) -> bool:
        return self.registry.delete(project_id)

    def update_status(self, project_id: str, status: str, last_sync: str | None = None) -> None:
        self.registry.update_status(project_id, status=status, last_sync=last_sync)

    def load_configs(
        self, project_id: str, project_path: str, resolve: bool = True
    ) -> tuple[list[UpstreamEntry], list[ForwardRule], AutomationConfig]:
        return self.registry.load_project_configs(project_id, project_path, resolve=resolve)


