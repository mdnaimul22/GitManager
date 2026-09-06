"""
Project CRUD and worker control endpoint tests.

Covers:
- GET /api/projects (list)
- GET /api/projects/{id} (detail)
- POST /api/projects (create)
- PUT /api/projects/{id} (update)
- DELETE /api/projects/{id} (delete)
- POST /api/projects/{id}/run (start worker)
- POST /api/projects/{id}/stop (stop worker)
- Live status consistency & atomic update checks
"""

import pytest


class TestListProjects:
    """GET /api/projects"""

    def test_list_returns_array(self, auth_client):
        resp = auth_client.get("/api/projects")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_list_contains_test_project(self, auth_client):
        resp = auth_client.get("/api/projects")
        names = [p["name"] for p in resp.json()]
        assert "Test Project" in names

    def test_list_project_has_required_fields(self, auth_client):
        resp = auth_client.get("/api/projects")
        project = resp.json()[0]
        required = {"id", "name", "path", "status"}
        assert required.issubset(project.keys())


class TestGetProject:
    """GET /api/projects/{id}"""

    def test_get_existing_project(self, auth_client):
        resp = auth_client.get("/api/projects/test-project")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "test-project"
        assert data["name"] == "Test Project"

    def test_get_includes_upstreams(self, auth_client):
        resp = auth_client.get("/api/projects/test-project")
        data = resp.json()
        assert "upstreams" in data
        assert len(data["upstreams"]) == 1
        assert data["upstreams"][0]["name"] == "upstream-a"

    def test_get_includes_forwards(self, auth_client):
        resp = auth_client.get("/api/projects/test-project")
        data = resp.json()
        assert "forwards" in data
        assert len(data["forwards"]) == 2

    def test_get_includes_git_config(self, auth_client):
        resp = auth_client.get("/api/projects/test-project")
        data = resp.json()
        assert data["git"]["branch"] == "dev"
        assert data["git"]["auto_push"] is False

    def test_get_includes_schedule(self, auth_client):
        resp = auth_client.get("/api/projects/test-project")
        data = resp.json()
        assert data["schedule"]["interval_minutes"] == 5

    def test_get_nonexistent_returns_404(self, auth_client):
        resp = auth_client.get("/api/projects/nonexistent-id")
        assert resp.status_code == 404


class TestCreateProject:
    """POST /api/projects"""

    def test_create_new_project(self, auth_client):
        resp = auth_client.post("/api/projects", json={
            "name": "New Temp",
            "path": "/tmp/new-temp-project",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "New Temp"
        assert data["path"] == "/tmp/new-temp-project"
        assert data["status"] == "idle"
        assert "id" in data

    def test_create_missing_name_fails(self, auth_client):
        resp = auth_client.post("/api/projects", json={"path": "/tmp/x"})
        assert resp.status_code == 422

    def test_create_missing_path_fails(self, auth_client):
        resp = auth_client.post("/api/projects", json={"name": "X"})
        assert resp.status_code == 422


class TestUpdateProject:
    """PUT /api/projects/{id}"""

    def test_update_git_config(self, auth_client):
        resp = auth_client.put("/api/projects/test-project", json={
            "git": {
                "auto_push": True,
                "branch": "staging",
                "commit_messages": {
                    "manual": "test commit",
                    "upstreams": {},
                },
            },
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["git"]["branch"] == "staging"
        assert data["git"]["auto_push"] is True

    def test_update_schedule(self, auth_client):
        resp = auth_client.put("/api/projects/test-project", json={
            "schedule": {"interval_minutes": 30, "poll_interval_seconds": 120},
        })
        assert resp.status_code == 200
        assert resp.json()["schedule"]["interval_minutes"] == 30

    def test_update_upstreams(self, auth_client):
        resp = auth_client.put("/api/projects/test-project", json={
            "upstreams": [
                {"name": "new-up", "path": "/tmp/.new-up", "url": "https://example.com/repo.git", "pull": False},
            ],
        })
        assert resp.status_code == 200
        assert len(resp.json()["upstreams"]) == 1
        assert resp.json()["upstreams"][0]["name"] == "new-up"

    def test_update_forwards_count(self, auth_client):
        forwards = [
            {"from": f"/src/skill-{i}", "to": f"/dst/skill-{i}", "enabled": True}
            for i in range(5)
        ]
        resp = auth_client.put("/api/projects/test-project", json={
            "forwards": forwards,
        })
        assert resp.status_code == 200
        assert len(resp.json()["forwards"]) == 5

    def test_update_then_get_consistency(self, auth_client):
        forwards = [
            {"from": "/x/a", "to": "/y/a", "enabled": True},
            {"from": "/x/b", "to": "/y/b", "enabled": False},
        ]
        put_resp = auth_client.put("/api/projects/test-project", json={
            "forwards": forwards,
        })
        get_resp = auth_client.get("/api/projects/test-project")

        assert put_resp.status_code == 200
        assert get_resp.status_code == 200
        assert len(put_resp.json()["forwards"]) == len(get_resp.json()["forwards"])

    def test_update_nonexistent_returns_404(self, auth_client):
        resp = auth_client.put("/api/projects/nonexistent-id", json={
            "git": {
                "auto_push": True,
                "branch": "x",
                "commit_messages": {"manual": "x", "upstreams": {}},
            },
        })
        assert resp.status_code == 404


class TestDeleteProject:
    """DELETE /api/projects/{id}"""

    def test_delete_existing(self, auth_client):
        resp = auth_client.post("/api/projects", json={
            "name": "Disposable",
            "path": "/tmp/disposable",
        })
        pid = resp.json()["id"]

        resp = auth_client.delete(f"/api/projects/{pid}")
        assert resp.status_code == 204

        resp = auth_client.get(f"/api/projects/{pid}")
        assert resp.status_code == 404

    def test_delete_nonexistent_returns_404(self, auth_client):
        resp = auth_client.delete("/api/projects/ghost-project")
        assert resp.status_code == 404


class TestWorkerControl:
    """POST /api/projects/{id}/run and /stop"""

    def test_run_project(self, auth_client):
        resp = auth_client.post("/api/projects/test-project/run")
        assert resp.status_code == 200
        assert resp.json()["status"] in ("started", "already_running")

    def test_stop_project(self, auth_client):
        resp = auth_client.post("/api/projects/test-project/stop")
        assert resp.status_code == 200
        assert resp.json()["status"] in ("stopped", "not_running")

    def test_run_nonexistent_returns_404(self, auth_client):
        resp = auth_client.post("/api/projects/ghost-id/run")
        assert resp.status_code == 404

    def test_run_then_stop_lifecycle(self, auth_client):
        auth_client.post("/api/projects/test-project/run")
        resp = auth_client.post("/api/projects/test-project/stop")
        assert resp.status_code == 200
        assert resp.json()["status"] in ("stopped", "not_running")

    def test_update_while_running_shows_running_status(self, auth_client):
        auth_client.post("/api/projects/test-project/run")

        resp = auth_client.put("/api/projects/test-project", json={
            "schedule": {"interval_minutes": 15, "poll_interval_seconds": 60},
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"

        auth_client.post("/api/projects/test-project/stop")

    def test_update_while_idle_shows_idle_status(self, auth_client):
        auth_client.post("/api/projects/test-project/stop")

        resp = auth_client.put("/api/projects/test-project", json={
            "schedule": {"interval_minutes": 10, "poll_interval_seconds": 60},
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "idle"

        # Restore default schedule
        auth_client.put("/api/projects/test-project", json={
            "schedule": {"interval_minutes": 5, "poll_interval_seconds": 30},
        })
