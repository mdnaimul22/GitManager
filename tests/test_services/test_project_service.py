"""
Project Service unit and integration tests.

Covers:
- load_project_configs: Parsing and resolution of per-project config files
- create_project, update_project, delete_project, update_project_status
"""

import pytest
from src.schema.models import ProjectCreate, ProjectUpdate, UpstreamEntry, ForwardRule
from src.services.project import (
    load_project_configs,
    create_project,
    get_project,
    update_project,
    delete_project,
    update_project_status,
)


class TestProjectService:
    """Tests for project service configuration and registry management."""

    def test_load_project_configs_returns_tuple_of_three(self):
        upstreams, forwards, automation = load_project_configs(
            "test-project", "/tmp/test-project"
        )
        assert isinstance(upstreams, list)
        assert isinstance(forwards, list)
        assert len(upstreams) == 1
        assert len(forwards) == 2

    def test_load_nonexistent_project_returns_empty_defaults(self):
        upstreams, forwards, automation = load_project_configs(
            "nonexistent-xyz", "/tmp/nowhere"
        )
        assert upstreams == []
        assert forwards == []

    def test_create_and_delete_project(self):
        meta = create_project(ProjectCreate(
            name="Service Test Proj",
            path="/tmp/service-test-proj",
        ))
        assert meta.id.startswith("service-test-proj")

        detail = get_project(meta.id)
        assert detail is not None
        assert detail.name == "Service Test Proj"

        deleted = delete_project(meta.id)
        assert deleted is True

        assert get_project(meta.id) is None

    def test_update_project_status(self):
        update_project_status("test-project", status="running", last_sync="2026-09-07T00:00:00")
        proj = get_project("test-project")
        assert proj.status == "running"
        assert proj.last_sync == "2026-09-07T00:00:00"

        # Restore
        update_project_status("test-project", status="idle", last_sync=None)
