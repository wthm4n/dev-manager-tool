"""
models/schemas.py
-----------------
Pydantic v2 schemas for FastAPI request validation and response serialisation.
Kept separate from ORM models (clean architecture: domain ≠ transport).
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from models.orm import EventType, ProjectType, SessionStatus


# ─────────────────────────────────────────────────────────────
# Project
# ─────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    path: str = Field(..., description="Absolute path to the project directory")
    name: Optional[str] = Field(None, description="Display name (defaults to folder name)")


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    path: str
    project_type: ProjectType
    has_git: bool
    git_remote: Optional[str]
    readme_generated: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


# ─────────────────────────────────────────────────────────────
# FileEvent
# ─────────────────────────────────────────────────────────────

class FileEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: str
    event_type: EventType
    file_path: str
    relative_path: Optional[str]
    is_directory: bool
    committed: bool
    occurred_at: datetime


# ─────────────────────────────────────────────────────────────
# CommitRecord
# ─────────────────────────────────────────────────────────────

class CommitRequest(BaseModel):
    project_id: str
    message_override: Optional[str] = Field(
        None, description="Skip AI generation and use this message directly"
    )


class CommitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: str
    sha: Optional[str]
    message: str
    diff_summary: Optional[str]
    files_changed: int
    insertions: int
    deletions: int
    ai_provider_used: Optional[str]
    committed_at: datetime


# ─────────────────────────────────────────────────────────────
# WorkSession
# ─────────────────────────────────────────────────────────────

class WorkSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: str
    status: SessionStatus
    started_at: datetime
    ended_at: Optional[datetime]
    active_minutes: float
    files_touched: int
    commits_made: int


# ─────────────────────────────────────────────────────────────
# ProductivityMetric
# ─────────────────────────────────────────────────────────────

class ProductivityMetricResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    files_per_hour: float
    commits_per_hour: float
    lines_added: int
    lines_removed: int
    most_edited_file: Optional[str]
    primary_language: Optional[str]
    computed_at: datetime


# ─────────────────────────────────────────────────────────────
# AI Generation Log
# ─────────────────────────────────────────────────────────────

class AIGenerationLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    model: str
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    latency_ms: Optional[float]
    task: str
    success: bool
    error_message: Optional[str]
    created_at: datetime


# ─────────────────────────────────────────────────────────────
# Generic helpers
# ─────────────────────────────────────────────────────────────

class MessageResponse(BaseModel):
    message: str
    success: bool = True


class PaginatedResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list
