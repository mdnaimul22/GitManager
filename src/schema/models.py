"""
Data contracts for GitManager — Pydantic models for all config entries.
No business logic allowed.
"""

import hashlib
import uuid
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


def generate_hash_id() -> str:
    """Generate an 8-character hash-based unique ID."""
    return hashlib.sha256(uuid.uuid4().bytes).hexdigest()[:8]


# ── Upstream ───────────────────────────────────────────────────────────────────

class UpstreamEntry(BaseModel):
    """A single upstream repository to track."""
    project_name: str = "unnamed"
    upstream_id: str = Field(default_factory=generate_hash_id)
    pull: bool = True
    sparse: bool = True
    blobless: bool = True
    branch: str = "main"
    path: str = ""
    url: str = ""

    model_config = {"populate_by_name": True, "extra": "ignore"}

    @model_validator(mode="before")
    @classmethod
    def _remap_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "name" in data and "project_name" not in data:
                data["project_name"] = data["name"]
            if "id" in data and "upstream_id" not in data:
                data["upstream_id"] = data["id"]
        return data

    @property
    def name(self) -> str:
        return self.project_name

    @name.setter
    def name(self, val: str) -> None:
        self.project_name = val

    @property
    def id(self) -> str:
        return self.upstream_id

    @id.setter
    def id(self, val: str) -> None:
        self.upstream_id = val


# ── Path Forwarding ───────────────────────────────────────────────────────────

class ForwardRule(BaseModel):
    """A single path-forwarding rule (from → to)."""
    enabled: bool = True
    project_name: str = ""
    upstream_id: str = ""
    forward_id: str = Field(default_factory=generate_hash_id)
    from_path: str = Field(default="", alias="from")
    to_path: str = Field(default="", alias="to")

    model_config = {"populate_by_name": True, "extra": "ignore"}

    @model_validator(mode="before")
    @classmethod
    def _remap_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "upstream" in data and "project_name" not in data:
                data["project_name"] = data["upstream"]
            if "id" in data and "forward_id" not in data:
                data["forward_id"] = data["id"]
        return data

    @property
    def id(self) -> str:
        return self.forward_id

    @id.setter
    def id(self, val: str) -> None:
        self.forward_id = val

    @property
    def upstream(self) -> str:
        return self.project_name

    @upstream.setter
    def upstream(self, val: str) -> None:
        self.project_name = val


# ── Managed Skills Memory ─────────────────────────────────────────────────────

class MemoryEntry(BaseModel):
    """Tracks a single managed forward destination in memory.json."""
    memory_id: str = Field(default_factory=generate_hash_id)
    upstream_id: str = ""
    forward_id: str = ""
    project_name: str = ""
    from_path: str = Field(default="", alias="from")
    to_path: str = Field(default="", alias="to")
    last_synced: str = ""

    model_config = {"populate_by_name": True, "extra": "ignore"}


# ── Automation Config ─────────────────────────────────────────────────────────

class CommitMessages(BaseModel):
    """Commit message templates."""
    manual: str = "chore: manual update of {count} file(s) [{datetime}]"
    upstreams: dict[str, str] = Field(default_factory=lambda: {
        "default": "sync: auto-update from {upstream_name} [{datetime}]"
    })


class GitConfig(BaseModel):
    """Git configuration."""
    auto_push: bool = True
    branch: str = "main"
    commit_messages: CommitMessages = Field(default_factory=CommitMessages)


class ScheduleConfig(BaseModel):
    """Schedule configuration."""
    run_at: Optional[str] = None
    interval_minutes: int = 10
    poll_interval_seconds: int = 60


class WebhookConfig(BaseModel):
    """Webhook configuration for instant sync."""
    enabled: bool = False
    secret: str = ""
    use_tunnel: bool = False
    tunnel_url: str = ""


class LoggingConfig(BaseModel):
    """Logging configuration."""
    level: str = "INFO"
    log_file: str = "{REPO_ROOT}/logs/sync.log"


class AutomationConfig(BaseModel):
    """Top-level automation structure."""
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    git: GitConfig = Field(default_factory=GitConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    webhook: WebhookConfig = Field(default_factory=WebhookConfig)


# ── Sync Result ───────────────────────────────────────────────────────────────

class SyncResult(BaseModel):
    """Summary of a single sync run."""
    pull_results: dict[str, bool] = Field(default_factory=dict)
    updated_upstreams: list[str] = Field(default_factory=list)
    copied_skills: list[str] = Field(default_factory=list)
    removed_orphans: list[str] = Field(default_factory=list)
    push_ok: bool = False


# ── Multi-Project ─────────────────────────────────────────────────────────────

ProjectStatus = Literal["idle", "running", "error", "paused"]


class ProjectMeta(BaseModel):
    """Project metadata stored in the global registry (projects.json)."""
    id: str
    name: str
    path: str
    status: ProjectStatus = "idle"
    last_sync: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""


class ProjectDetail(BaseModel):
    """Full project config — meta + per-project data (API response)."""
    id: str
    name: str
    path: str
    status: ProjectStatus = "idle"
    last_sync: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    upstreams: list[UpstreamEntry] = Field(default_factory=list)
    forwards: list[ForwardRule] = Field(default_factory=list)
    git: GitConfig = Field(default_factory=GitConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    webhook: WebhookConfig = Field(default_factory=WebhookConfig)
    last_result: Optional[SyncResult] = None


class ProjectCreate(BaseModel):
    """API input for creating a project."""
    name: str
    path: str


class ProjectUpdate(BaseModel):
    """API input for updating project config."""
    upstreams: Optional[list[UpstreamEntry]] = None
    forwards: Optional[list[ForwardRule]] = None
    git: Optional[GitConfig] = None
    schedule: Optional[ScheduleConfig] = None
    webhook: Optional[WebhookConfig] = None


# ── Authentication ────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    """API input for login."""
    username: str
    password: str


# ── Tunnel / System ───────────────────────────────────────────────────────────

class TunnelStatus(BaseModel):
    """Tailscale / tunnel connection status."""
    installed: bool = False
    running: bool = False
    funnel_active: bool = False
    domain: Optional[str] = None
    funnel_url: Optional[str] = None
    port: int = 8000
    error: Optional[str] = None


class FunnelToggleRequest(BaseModel):
    """API input for toggling Tailscale funnel."""
    enable: bool = Field(default=True, description="Enable or disable Tailscale funnel")

    model_config = {"populate_by_name": True, "extra": "ignore"}

    @model_validator(mode="before")
    @classmethod
    def _remap_enable(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "enabled" in data and "enable" not in data:
                data["enable"] = data["enabled"]
        return data


TunnelToggleRequest = FunnelToggleRequest


class FunnelToggleResponse(BaseModel):
    """API response after toggling Tailscale funnel."""
    status: str = "ok"
    message: str = ""
    tunnel: TunnelStatus


