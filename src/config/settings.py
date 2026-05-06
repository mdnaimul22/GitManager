from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .paths import PROJECT_ROOT


class Settings(BaseSettings):
    PROJECT_NAME: str = "GitManager"
    VERSION: str = "2.0.0"
    ENV: str = Field(default="development", validation_alias="APP_ENV")

    RAW_LOG_DIR: str = Field(..., validation_alias="LOG_DIR")
    RAW_DATA_DIR: str = Field(..., validation_alias="DATA_DIR")

    def _resolve(self, val: str) -> Path:

        val = val.strip()
        # Handle /.hidden -> ~/.hidden (Forgotten tilde)
        if val.startswith("/."):
            val = "~/" + val[2:] if val.startswith("/./") else "~/" + val[1:]

        # Handle .hidden (if it's not ./ or ../) -> treat as home relative for our tools
        if val.startswith(".") and not val.startswith("./") and not val.startswith("../"):
            val = "~/" + val

        p = Path(val).expanduser()
        return p if p.is_absolute() else PROJECT_ROOT / p


    @property
    def LOG_DIR(self) -> Path:
        return self._resolve(self.RAW_LOG_DIR)

    @property
    def DATA_DIR(self) -> Path:
        return self._resolve(self.RAW_DATA_DIR)

    @property
    def is_production(self) -> bool:
        return self.ENV.lower() == "production"

    @property
    def is_development(self) -> bool:
        return self.ENV.lower() == "development"

    # ── API Configuration ─────────────────────────────────────────────────
    API_HOST: str = Field(..., validation_alias="API_HOST")
    API_PORT: int = Field(..., validation_alias="API_PORT")

    # ── Git Defaults (for new projects) ───────────────────────────────────
    GIT_AUTO_PUSH: bool = Field(..., validation_alias="GIT_AUTO_PUSH")
    GIT_BRANCH: str = Field(..., validation_alias="GIT_BRANCH")

    # ── Schedule Defaults (for new projects) ──────────────────────────────
    SYNC_INTERVAL_MINUTES: int = Field(..., validation_alias="SYNC_INTERVAL_MINUTES")
    SYNC_POLL_SECONDS: int = Field(..., validation_alias="SYNC_POLL_SECONDS")

    # ── Authentication ────────────────────────────────────────────────────
    GM_USERNAME: str = Field(..., validation_alias="GM_USERNAME")
    GM_PASSWORD: str = Field(..., validation_alias="GM_PASSWORD")

    # ── Per-project file names (inside data/{project_id}/) ────────────────
    PROJECTS_FILE: str = "projects.json"
    UPSTREAM_FILE: str = "upstream.json"
    FORWARD_FILE: str = "forward.json"
    AUTOMATION_FILE: str = "automation.json"
    MEMORY_FILE: str = "memory.json"

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


Settings = Settings()