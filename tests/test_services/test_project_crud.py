"""
Comprehensive CRUD & Data Integrity tests for Project Service.

Verifies:
- Read, Write, Update, Edit, Delete on every field of upstreams and forwards.
- Ensures renaming an upstream synchronizes forward.json correctly on disk.
- Ensures deleting an upstream removes it cleanly and unlinks forwards without ghost IDs.
- Ensures deleting a forward removes it cleanly without affecting others.
- Ensures no mirage / merging / collisions across distinct entries.
"""

import pytest
from src.config import Settings, exists, read_json
from src.schema.models import (
    AutomationConfig,
    ForwardRule,
    GitConfig,
    ProjectCreate,
    ProjectUpdate,
    ScheduleConfig,
    UpstreamEntry,
    WebhookConfig,
)
from src.services.project import ProjectService

_svc = ProjectService()


@pytest.fixture
def clean_test_project():
    """Create a temporary project for thorough CRUD testing and clean up afterwards."""
    meta = _svc.create(ProjectCreate(
        name="CRUD Integrity Test Project",
        path="/tmp/crud-integrity-test-proj",
    ))
    proj_id = meta.id
    yield proj_id
    _svc.delete(proj_id)


class TestProjectCrudIntegrity:
    """Test full CRUD operations on all fields with direct disk verification."""

    def test_write_and_read_all_fields_on_disk(self, clean_test_project):
        proj_id = clean_test_project

        # 1. WRITE: Add upstreams and forwards with all explicit fields
        up1 = UpstreamEntry(
            project_name="agent-zero",
            pull=True,
            sparse=True,
            blobless=True,
            branch="main",
            path=".data/.agent-zero_skills",
            url="https://github.com/agent0ai/agent-zero.git",
        )
        up2 = UpstreamEntry(
            project_name="heygen-com",
            pull=False,
            sparse=False,
            blobless=False,
            branch="develop",
            path=".data/.heygen_skills",
            url="https://github.com/heygen-com/skills.git",
        )

        fwd1 = ForwardRule(
            enabled=True,
            project_name="agent-zero",
            upstream_id=up1.upstream_id,
            from_path=".data/.agent-zero_skills/skills",
            to_path="skills/storage/agent-zero",
        )
        fwd2 = ForwardRule(
            enabled=False,
            project_name="heygen-com",
            upstream_id=up2.upstream_id,
            from_path=".data/.heygen_skills/core",
            to_path="skills/storage/heygen",
        )

        
        _svc.update(proj_id, ProjectUpdate(
            upstreams=[up1, up2],
            forwards=[fwd1, fwd2],
            git=GitConfig(branch="master", auto_push=False),
            schedule=ScheduleConfig(interval_minutes=15, poll_interval_seconds=45),
            webhook=WebhookConfig(enabled=True, secret="sec123"),
        ))

        # 2. READ DIRECTLY FROM DISK JSON FILES
        up_disk = read_json(f"{Settings.RAW_DATA_DIR}/{proj_id}/upstream.json")
        fwd_disk = read_json(f"{Settings.RAW_DATA_DIR}/{proj_id}/forward.json")
        auto_disk = read_json(f"{Settings.RAW_DATA_DIR}/{proj_id}/automation.json")

        assert len(up_disk["upstreams"]) == 2
        disk_up1 = up_disk["upstreams"][0]
        assert disk_up1["project_name"] == "agent-zero"
        assert disk_up1["upstream_id"] == up1.upstream_id
        assert disk_up1["pull"] is True
        assert disk_up1["sparse"] is True
        assert disk_up1["blobless"] is True
        assert disk_up1["branch"] == "main"
        assert disk_up1["path"] == ".data/.agent-zero_skills"
        assert disk_up1["url"] == "https://github.com/agent0ai/agent-zero.git"

        disk_up2 = up_disk["upstreams"][1]
        assert disk_up2["project_name"] == "heygen-com"
        assert disk_up2["upstream_id"] == up2.upstream_id
        assert disk_up2["pull"] is False
        assert disk_up2["sparse"] is False
        assert disk_up2["blobless"] is False
        assert disk_up2["branch"] == "develop"
        assert disk_up2["path"] == ".data/.heygen_skills"
        assert disk_up2["url"] == "https://github.com/heygen-com/skills.git"

        assert len(fwd_disk["forwards"]) == 2
        disk_fwd1 = fwd_disk["forwards"][0]
        assert disk_fwd1["enabled"] is True
        assert disk_fwd1["project_name"] == "agent-zero"
        assert disk_fwd1["upstream_id"] == up1.upstream_id
        assert disk_fwd1["forward_id"] == fwd1.forward_id
        assert disk_fwd1["from"] == ".data/.agent-zero_skills/skills"
        assert disk_fwd1["to"] == "skills/storage/agent-zero"

        disk_fwd2 = fwd_disk["forwards"][1]
        assert disk_fwd2["enabled"] is False
        assert disk_fwd2["project_name"] == "heygen-com"
        assert disk_fwd2["upstream_id"] == up2.upstream_id
        assert disk_fwd2["forward_id"] == fwd2.forward_id
        assert disk_fwd2["from"] == ".data/.heygen_skills/core"
        assert disk_fwd2["to"] == "skills/storage/heygen"

        assert auto_disk["git"]["branch"] == "master"
        assert auto_disk["git"]["auto_push"] is False
        assert auto_disk["schedule"]["interval_minutes"] == 15
        assert auto_disk["webhook"]["enabled"] is True
        assert auto_disk["webhook"]["secret"] == "sec123"

    def test_update_upstream_project_name_syncs_forward_json_on_disk(self, clean_test_project):
        """
        Renaming 'heygen-com' to 'heygen-v2' must update upstream.json AND
        all forwards in forward.json linked to that upstream_id, while
        leaving agent-zero and other rules untouched (no merging).
        """
        proj_id = clean_test_project

        up1 = UpstreamEntry(project_name="agent-zero", path=".data/up1", url="https://github.com/1.git")
        up2 = UpstreamEntry(project_name="heygen-com", path=".data/up2", url="https://github.com/2.git")

        fwd1 = ForwardRule(project_name="agent-zero", upstream_id=up1.upstream_id, from_path=".data/up1/a", to_path="skills/a")
        fwd2 = ForwardRule(project_name="heygen-com", upstream_id=up2.upstream_id, from_path=".data/up2/b", to_path="skills/b")
        fwd3 = ForwardRule(project_name="heygen-com", upstream_id=up2.upstream_id, from_path=".data/up2/c", to_path="skills/c")

        
        _svc.update(proj_id, ProjectUpdate(
            upstreams=[up1, up2],
            forwards=[fwd1, fwd2, fwd3],
        ))

        # ACTION: Rename heygen-com to heygen-v2 (update only upstreams, simulating upstream edit)
        up2_renamed = UpstreamEntry(
            project_name="heygen-v2",
            upstream_id=up2.upstream_id,
            path=up2.path,
            url=up2.url,
            branch=up2.branch,
        )
        
        _svc.update(proj_id, ProjectUpdate(
            upstreams=[up1, up2_renamed],
        ))

        # VERIFY ON DISK: upstream.json
        up_disk = read_json(f"{Settings.RAW_DATA_DIR}/{proj_id}/upstream.json")
        assert up_disk["upstreams"][0]["project_name"] == "agent-zero"
        assert up_disk["upstreams"][1]["project_name"] == "heygen-v2"
        assert up_disk["upstreams"][1]["upstream_id"] == up2.upstream_id

        # VERIFY ON DISK: forward.json must have synced project_name for heygen forwards
        fwd_disk = read_json(f"{Settings.RAW_DATA_DIR}/{proj_id}/forward.json")
        assert len(fwd_disk["forwards"]) == 3
        assert fwd_disk["forwards"][0]["project_name"] == "agent-zero"
        assert fwd_disk["forwards"][0]["upstream_id"] == up1.upstream_id

        # Both heygen forwards updated their project_name
        assert fwd_disk["forwards"][1]["project_name"] == "heygen-v2"
        assert fwd_disk["forwards"][1]["upstream_id"] == up2.upstream_id
        assert fwd_disk["forwards"][1]["to"] == "skills/b"

        assert fwd_disk["forwards"][2]["project_name"] == "heygen-v2"
        assert fwd_disk["forwards"][2]["upstream_id"] == up2.upstream_id
        assert fwd_disk["forwards"][2]["to"] == "skills/c"

    def test_edit_each_individual_upstream_field(self, clean_test_project):
        """Ensure every single field of an upstream can be edited and saved accurately on disk."""
        proj_id = clean_test_project

        up = UpstreamEntry(
            project_name="base-up",
            branch="main",
            path=".data/base",
            url="https://github.com/base.git",
            pull=True,
            sparse=True,
            blobless=True,
        )
        
        _svc.update(proj_id, ProjectUpdate(upstreams=[up]))

        # Edit branch
        up.branch = "feature/skills-v2"
        
        _svc.update(proj_id, ProjectUpdate(upstreams=[up]))
        assert read_json(f"{Settings.RAW_DATA_DIR}/{proj_id}/upstream.json")["upstreams"][0]["branch"] == "feature/skills-v2"

        # Edit path
        up.path = ".data/new_path"
        
        _svc.update(proj_id, ProjectUpdate(upstreams=[up]))
        assert read_json(f"{Settings.RAW_DATA_DIR}/{proj_id}/upstream.json")["upstreams"][0]["path"] == ".data/new_path"

        # Edit url
        up.url = "https://github.com/new-url/repo.git"
        
        _svc.update(proj_id, ProjectUpdate(upstreams=[up]))
        assert read_json(f"{Settings.RAW_DATA_DIR}/{proj_id}/upstream.json")["upstreams"][0]["url"] == "https://github.com/new-url/repo.git"

        # Toggle pull
        up.pull = False
        
        _svc.update(proj_id, ProjectUpdate(upstreams=[up]))
        assert read_json(f"{Settings.RAW_DATA_DIR}/{proj_id}/upstream.json")["upstreams"][0]["pull"] is False

        # Toggle sparse
        up.sparse = False
        
        _svc.update(proj_id, ProjectUpdate(upstreams=[up]))
        assert read_json(f"{Settings.RAW_DATA_DIR}/{proj_id}/upstream.json")["upstreams"][0]["sparse"] is False

        # Toggle blobless
        up.blobless = False
        
        _svc.update(proj_id, ProjectUpdate(upstreams=[up]))
        assert read_json(f"{Settings.RAW_DATA_DIR}/{proj_id}/upstream.json")["upstreams"][0]["blobless"] is False

    def test_edit_each_individual_forward_field(self, clean_test_project):
        """Ensure every single field of a forward rule can be edited and saved accurately on disk."""
        proj_id = clean_test_project

        up1 = UpstreamEntry(project_name="up-one", path=".data/one", url="https://github.com/one.git")
        up2 = UpstreamEntry(project_name="up-two", path=".data/two", url="https://github.com/two.git")

        fwd = ForwardRule(
            enabled=True,
            project_name="up-one",
            upstream_id=up1.upstream_id,
            from_path=".data/one/skills",
            to_path="skills/storage/one",
        )
        
        _svc.update(proj_id, ProjectUpdate(upstreams=[up1, up2], forwards=[fwd]))

        # Edit from_path
        fwd.from_path = ".data/one/new_subpath"
        
        _svc.update(proj_id, ProjectUpdate(forwards=[fwd]))
        data = read_json(f"{Settings.RAW_DATA_DIR}/{proj_id}/forward.json")["forwards"][0]
        assert data["from"] == ".data/one/new_subpath"

        # Edit to_path
        fwd.to_path = "skills/storage/custom_dest"
        
        _svc.update(proj_id, ProjectUpdate(forwards=[fwd]))
        data = read_json(f"{Settings.RAW_DATA_DIR}/{proj_id}/forward.json")["forwards"][0]
        assert data["to"] == "skills/storage/custom_dest"

        # Toggle enabled
        fwd.enabled = False
        
        _svc.update(proj_id, ProjectUpdate(forwards=[fwd]))
        data = read_json(f"{Settings.RAW_DATA_DIR}/{proj_id}/forward.json")["forwards"][0]
        assert data["enabled"] is False

        # Reassign to up2 (switch upstream)
        fwd.upstream_id = up2.upstream_id
        
        _svc.update(proj_id, ProjectUpdate(forwards=[fwd]))
        data = read_json(f"{Settings.RAW_DATA_DIR}/{proj_id}/forward.json")["forwards"][0]
        assert data["upstream_id"] == up2.upstream_id
        assert data["project_name"] == "up-two"  # auto-synced!

    def test_delete_upstream_removes_from_disk_and_unlinks_forwards(self, clean_test_project):
        """Deleting an upstream must remove it from upstream.json and clear upstream_id on its forwards."""
        proj_id = clean_test_project

        up1 = UpstreamEntry(project_name="keep-me", path=".data/keep", url="https://github.com/keep.git")
        up2 = UpstreamEntry(project_name="delete-me", path=".data/del", url="https://github.com/del.git")

        fwd_keep = ForwardRule(project_name="keep-me", upstream_id=up1.upstream_id, from_path=".data/keep/s", to_path="skills/keep")
        fwd_del = ForwardRule(project_name="delete-me", upstream_id=up2.upstream_id, from_path=".data/del/s", to_path="skills/del")

        
        _svc.update(proj_id, ProjectUpdate(
            upstreams=[up1, up2],
            forwards=[fwd_keep, fwd_del],
        ))

        # ACTION: Delete up2 by submitting only up1
        
        _svc.update(proj_id, ProjectUpdate(upstreams=[up1]))

        # VERIFY upstream.json
        up_disk = read_json(f"{Settings.RAW_DATA_DIR}/{proj_id}/upstream.json")
        assert len(up_disk["upstreams"]) == 1
        assert up_disk["upstreams"][0]["project_name"] == "keep-me"

        # VERIFY forward.json
        fwd_disk = read_json(f"{Settings.RAW_DATA_DIR}/{proj_id}/forward.json")
        assert len(fwd_disk["forwards"]) == 2
        # keep-me is untouched
        assert fwd_disk["forwards"][0]["project_name"] == "keep-me"
        assert fwd_disk["forwards"][0]["upstream_id"] == up1.upstream_id
        # delete-me is cleanly unlinked (no ghost / dangling upstream_id)
        assert fwd_disk["forwards"][1]["upstream_id"] == ""
        assert fwd_disk["forwards"][1]["project_name"] == ""
        assert fwd_disk["forwards"][1]["to"] == "skills/del"

    def test_delete_forward_removes_from_disk(self, clean_test_project):
        """Deleting a forward must remove it completely from forward.json."""
        proj_id = clean_test_project

        up = UpstreamEntry(project_name="my-up", path=".data/my", url="https://github.com/my.git")
        f1 = ForwardRule(project_name="my-up", upstream_id=up.upstream_id, from_path=".data/my/1", to_path="skills/1")
        f2 = ForwardRule(project_name="my-up", upstream_id=up.upstream_id, from_path=".data/my/2", to_path="skills/2")
        f3 = ForwardRule(project_name="my-up", upstream_id=up.upstream_id, from_path=".data/my/3", to_path="skills/3")

        
        _svc.update(proj_id, ProjectUpdate(upstreams=[up], forwards=[f1, f2, f3]))
        assert len(read_json(f"{Settings.RAW_DATA_DIR}/{proj_id}/forward.json")["forwards"]) == 3

        # ACTION: Delete f2
        
        _svc.update(proj_id, ProjectUpdate(forwards=[f1, f3]))

        # VERIFY: f2 is gone, f1 and f3 remain intact
        fwd_disk = read_json(f"{Settings.RAW_DATA_DIR}/{proj_id}/forward.json")
        assert len(fwd_disk["forwards"]) == 2
        assert fwd_disk["forwards"][0]["forward_id"] == f1.forward_id
        assert fwd_disk["forwards"][0]["to"] == "skills/1"
        assert fwd_disk["forwards"][1]["forward_id"] == f3.forward_id
        assert fwd_disk["forwards"][1]["to"] == "skills/3"

    def test_delete_project_removes_directory_and_registry(self):
        """Deleting a project removes its entry from projects.json and deletes its directory on disk."""
        meta = _svc.create(ProjectCreate(
            name="Temporary To Delete",
            path="/tmp/temporary-to-delete",
        ))
        proj_id = meta.id
        proj_dir = f"{Settings.RAW_DATA_DIR}/{proj_id}"
        assert exists(proj_dir)

        # Delete
        success = _svc.delete(proj_id)
        assert success is True
        assert not exists(proj_dir)
        assert _svc.get(proj_id) is None
