"""
config/settings.py
------------------
Centralised application settings loaded from environment variables / .env file.
All configuration is typed and validated by Pydantic v2 BaseSettings.
"""

from __future__ import annotations

import os
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class AppEnvironment(str, Enum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"


class AIProvider(str, Enum):
    OLLAMA = "ollama"
    OPENAI = "openai"


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class Settings(BaseSettings):
    """
    All settings sourced from environment variables.
    Values in .env override defaults.
    """

    # ── Application ──────────────────────────────────────────────
    app_name: str = Field(default="DevManagerAI", alias="APP_NAME")
    app_env: AppEnvironment = Field(default=AppEnvironment.DEVELOPMENT, alias="APP_ENV")
    app_port: int = Field(default=8000, alias="APP_PORT")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    debug: bool = Field(default=False, alias="DEBUG")
    log_level: LogLevel = Field(default=LogLevel.INFO, alias="LOG_LEVEL")

    # ── Database ─────────────────────────────────────────────────
    database_url: str = Field(
        default="sqlite:///./devmanager.db", alias="DATABASE_URL"
    )

    # ── AI Provider ──────────────────────────────────────────────
    ai_provider: AIProvider = Field(default=AIProvider.OLLAMA, alias="AI_PROVIDER")

    ollama_base_url: str = Field(
        default="http://localhost:11434", alias="OLLAMA_BASE_URL"
    )
    ollama_model: str = Field(default="llama3", alias="OLLAMA_MODEL")

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(
        default="https://api.openai.com/v1", alias="OPENAI_BASE_URL"
    )
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")

    # ── File Watcher ─────────────────────────────────────────────
    watched_paths_raw: str = Field(default="", alias="WATCHED_PATHS")
    ignored_extensions_raw: str = Field(
        default=".pyc,.pyo,.swp,.swo,.DS_Store", alias="IGNORED_EXTENSIONS"
    )
    ignored_dirs_raw: str = Field(
        default="__pycache__,node_modules,.git,.venv,dist,build,.next",
        alias="IGNORED_DIRS",
    )

    # ── Git ──────────────────────────────────────────────────────
    git_author_name: str = Field(default="DevManager AI", alias="GIT_AUTHOR_NAME")
    git_author_email: str = Field(
        default="devmanager@local", alias="GIT_AUTHOR_EMAIL"
    )

    # ── Productivity ─────────────────────────────────────────────
    session_idle_timeout_minutes: int = Field(
        default=15, alias="SESSION_IDLE_TIMEOUT_MINUTES"
    )
    metrics_flush_interval_seconds: int = Field(
        default=60, alias="METRICS_FLUSH_INTERVAL_SECONDS"
    )

    model_config = {
        "env_file": str(Path(__file__).parent.parent / ".env"),
        "env_file_encoding": "utf-8",
        "populate_by_name": True,
    }

    # ── Computed helpers ─────────────────────────────────────────

    @property
    def watched_paths(self) -> List[Path]:
        """Return list of Path objects for directories to watch."""
        if not self.watched_paths_raw:
            return []
        return [
            Path(p.strip())
            for p in self.watched_paths_raw.split(",")
            if p.strip()
        ]

    @property
    def ignored_extensions(self) -> List[str]:
        return [e.strip() for e in self.ignored_extensions_raw.split(",") if e.strip()]

    @property
    def ignored_dirs(self) -> List[str]:
        return [d.strip() for d in self.ignored_dirs_raw.split(",") if d.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == AppEnvironment.PRODUCTION

    @property
    def project_root(self) -> Path:
        return Path(__file__).parent.parent


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return a cached singleton Settings instance.
    Use dependency injection in FastAPI via Depends(get_settings).
    """
    return Settings()