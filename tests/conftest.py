"""
Shared fixtures for GitManager tests.
"""

import json

import pytest
from fastapi.testclient import TestClient

from src.config import Settings
from src.core import WorkerPool
from src.routers import set_pool


@pytest.fixture(scope="session", autouse=True)
def _patch_data_dir(tmp_path_factory):
    """Redirect DATA_DIR to a temp directory with test data."""
    test_data = tmp_path_factory.mktemp("gm_test_data")

    # Global projects registry
    projects = [
        {
            "id": "test-project",
            "name": "Test Project",
            "path": "/tmp/test-project",
            "status": "idle",
            "last_sync": None,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }
    ]
    (test_data / "projects.json").write_text(json.dumps(projects, indent=2))

    # Per-project config directory
    proj_dir = test_data / "test-project"
    proj_dir.mkdir()
    (proj_dir / "upstream.json").write_text(json.dumps({
        "upstreams": [
            {"name": "upstream-a", "path": "/tmp/.upstream-a",
             "url": "https://github.com/test/a.git", "pull": True},
        ]
    }))
    (proj_dir / "forward.json").write_text(json.dumps({
        "forwards": [
            {"from": "/tmp/.upstream-a/skills/one", "to": "/tmp/test-project/skills/one", "enabled": True},
            {"from": "/tmp/.upstream-a/skills/two", "to": "/tmp/test-project/skills/two", "enabled": False},
        ]
    }))
    (proj_dir / "automation.json").write_text(json.dumps({
        "schedule": {"interval_minutes": 5, "poll_interval_seconds": 30},
        "git": {
            "auto_push": False, "branch": "dev",
            "commit_messages": {"manual": "test: {count} files [{datetime}]", "upstreams": {}}
        },
        "logging": {"level": "DEBUG", "log_file": "test.log"},
    }))
    (proj_dir / "memory.json").write_text(json.dumps({"managed_skills": ["skill-a"]}))

    # Patch Settings
    original = Settings.RAW_DATA_DIR
    Settings.RAW_DATA_DIR = str(test_data)

    yield test_data

    Settings.RAW_DATA_DIR = original


@pytest.fixture()
def client():
    """Authenticated-ready TestClient with WorkerPool injected."""
    from main import app

    # Inject worker pool (normally done in lifespan)
    pool = WorkerPool()
    set_pool(pool)
    app.state.pool = pool

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c

    pool.stop_all()


@pytest.fixture()
def auth_client(client):
    """Pre-authenticated TestClient."""
    resp = client.post("/api/auth/login", json={
        "username": Settings.GM_USERNAME,
        "password": Settings.GM_PASSWORD,
    })
    assert resp.status_code == 200, f"Login failed: {resp.json()}"
    return client
