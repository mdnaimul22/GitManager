"""
Data contracts for GitManager — Pydantic models for all config entries.
No business logic allowed.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field


# ── Upstream ───────────────────────────────────────────────────────────────────

class UpstreamEntry(BaseModel):
    """A single upstream repository to track."""
    name: str = "unnamed"
    path: str = ""
    url: str = ""
    branch: str = "main"
    pull: bool = True


# ── Path Forwarding ───────────────────────────────────────────────────────────

class ForwardRule(BaseModel):
    """A single path-forwarding rule (from → to)."""
    from_path: str = Field(default="", alias="from")
    to_path: str = Field(default="", alias="to")
    enabled: bool = True

    model_config = {"populate_by_name": True}


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


class LoggingConfig(BaseModel):
    """Logging configuration."""
    level: str = "INFO"
    log_file: str = "{REPO_ROOT}/logs/sync.log"


class AutomationConfig(BaseModel):
    """Top-level automation structure."""
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    git: GitConfig = Field(default_factory=GitConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


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


# ── Authentication ────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    """API input for login."""
    username: str
    password: str
