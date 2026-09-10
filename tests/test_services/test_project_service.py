"""
Project Service unit and integration tests.

Covers:
- ProjectService.load_configs: Parsing and resolution of per-project config files
- ProjectService.create/update/delete/update_status
"""

import pytest
from src.schema.models import ProjectCreate, ProjectUpdate, UpstreamEntry, ForwardRule
from src.services.project import ProjectService

_svc = ProjectService()


class TestProjectService:
    """Tests for project service configuration and registry management."""

    def test_load_project_configs_returns_tuple_of_three(self):
        upstreams, forwards, automation = _svc.load_configs(
            "test-project", "/tmp/test-project"
        )
        assert isinstance(upstreams, list)
        assert isinstance(forwards, list)
        assert len(upstreams) == 1
        assert len(forwards) == 2

    def test_load_nonexistent_project_returns_empty_defaults(self):
        upstreams, forwards, automation = _svc.load_configs(
            "nonexistent-xyz", "/tmp/nowhere"
        )
        assert upstreams == []
        assert forwards == []

    def test_create_and_delete_project(self):
        meta = _svc.create(ProjectCreate(
            name="Service Test Proj",
            path="/tmp/service-test-proj",
        ))
        assert meta.id.startswith("service-test-proj")

        detail = _svc.get(meta.id)
        assert detail is not None
        assert detail.name == "Service Test Proj"

        deleted = _svc.delete(meta.id)
        assert deleted is True

        assert _svc.get(meta.id) is None

    def test_update_project_status(self):
        _svc.update_status("test-project", status="running", last_sync="2026-09-07T00:00:00")
        proj = _svc.get("test-project")
        assert proj.status == "running"
        assert proj.last_sync == "2026-09-07T00:00:00"

        # Restore
        _svc.update_status("test-project", status="idle", last_sync=None)

    def test_update_project_assigns_8char_hash_ids_and_deduplicates_forwards(self):
        meta = _svc.create(ProjectCreate(
            name="Hash ID Test Proj",
            path="/tmp/hash-id-test-proj",
        ))
        try:
            up1 = UpstreamEntry(name="up1", path=".data/up1", url="https://github.com/a/b.git")
            f1 = ForwardRule(from_path=".data/up1/skills", to_path="skills/up1", upstream_id=up1.id)
            f_duplicate = ForwardRule(from_path=".data/up1/skills", to_path="skills/up1", upstream_id=up1.id)

            _svc.update(meta.id, ProjectUpdate(
                upstreams=[up1],
                forwards=[f1, f_duplicate],
            ))

            detail = _svc.get(meta.id)
            assert detail is not None
            assert len(detail.upstreams) == 1
            assert len(detail.upstreams[0].id) == 8
            assert len(detail.forwards) == 1  # Deduplicated!
            assert detail.forwards[0].upstream_id == detail.upstreams[0].id
            assert len(detail.forwards[0].id) == 8
        finally:
            _svc.delete(meta.id)
