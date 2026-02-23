"""
models/orm.py
-------------
All SQLAlchemy ORM models for DevManager AI.

Schema:
    Project          – a monitored folder / git repo
    FileEvent        – a filesystem change detected by watchdog
    CommitRecord     – an AI-generated commit that was applied
    WorkSession      – a contiguous block of developer activity
    ProductivityMetric – aggregated stats per session
    AIGenerationLog  – every LLM call made (for auditing / cost tracking)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base


# ─────────────────────────────────────────────────────────────
# Enumerations
# ─────────────────────────────────────────────────────────────

class ProjectType(str, PyEnum):
    REACT = "react"
    NEXTJS = "nextjs"
    NODE = "node"
    PYTHON = "python"
    ROBLOX = "roblox"
    RUST = "rust"
    GO = "go"
    JAVA = "java"
    DOTNET = "dotnet"
    UNKNOWN = "unknown"


class EventType(str, PyEnum):
    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"
    MOVED = "moved"


class SessionStatus(str, PyEnum):
    ACTIVE = "active"
    IDLE = "idle"
    CLOSED = "closed"


# ─────────────────────────────────────────────────────────────
# Project
# ─────────────────────────────────────────────────────────────

class Project(Base):
    """
    Represents a monitored directory that may contain a git repository.
    One project per top-level watched folder.
    """

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False)
    project_type: Mapped[str] = mapped_column(
        Enum(ProjectType), nullable=False, default=ProjectType.UNKNOWN
    )
    has_git: Mapped[bool] = mapped_column(Boolean, default=False)
    git_remote: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    readme_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    file_events: Mapped[List["FileEvent"]] = relationship(
        "FileEvent", back_populates="project", cascade="all, delete-orphan"
    )
    commit_records: Mapped[List["CommitRecord"]] = relationship(
        "CommitRecord", back_populates="project", cascade="all, delete-orphan"
    )
    work_sessions: Mapped[List["WorkSession"]] = relationship(
        "WorkSession", back_populates="project", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Project name={self.name!r} type={self.project_type} path={self.path!r}>"


# ─────────────────────────────────────────────────────────────
# FileEvent
# ─────────────────────────────────────────────────────────────

class FileEvent(Base):
    """
    Raw filesystem event recorded by the watchdog observer.
    Batched into commits after a debounce period.
    """

    __tablename__ = "file_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(Enum(EventType), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    is_directory: Mapped[bool] = mapped_column(Boolean, default=False)
    # Relative path from project root for display
    relative_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    committed: Mapped[bool] = mapped_column(Boolean, default=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="file_events")

    def __repr__(self) -> str:
        return f"<FileEvent {self.event_type} {self.relative_path!r}>"


# ─────────────────────────────────────────────────────────────
# CommitRecord
# ─────────────────────────────────────────────────────────────

class CommitRecord(Base):
    """
    A git commit that DevManager AI created on behalf of the developer.
    Stores both the AI-generated message and the resulting git SHA.
    """

    __tablename__ = "commit_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    sha: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    diff_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    files_changed: Mapped[int] = mapped_column(Integer, default=0)
    insertions: Mapped[int] = mapped_column(Integer, default=0)
    deletions: Mapped[int] = mapped_column(Integer, default=0)
    ai_provider_used: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    committed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="commit_records")

    def __repr__(self) -> str:
        return f"<CommitRecord sha={self.sha!r} files={self.files_changed}>"


# ─────────────────────────────────────────────────────────────
# WorkSession
# ─────────────────────────────────────────────────────────────

class WorkSession(Base):
    """
    A contiguous block of developer activity inferred from file events.
    Closed when idle for SESSION_IDLE_TIMEOUT_MINUTES.
    """

    __tablename__ = "work_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        Enum(SessionStatus), nullable=False, default=SessionStatus.ACTIVE
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Total active minutes (excluding idle gaps)
    active_minutes: Mapped[float] = mapped_column(Float, default=0.0)
    files_touched: Mapped[int] = mapped_column(Integer, default=0)
    commits_made: Mapped[int] = mapped_column(Integer, default=0)

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="work_sessions")
    metrics: Mapped[Optional["ProductivityMetric"]] = relationship(
        "ProductivityMetric", back_populates="session", uselist=False,
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<WorkSession id={self.id} project={self.project_id} status={self.status}>"


# ─────────────────────────────────────────────────────────────
# ProductivityMetric
# ─────────────────────────────────────────────────────────────

class ProductivityMetric(Base):
    """
    Aggregated productivity statistics for a closed WorkSession.
    Computed once when the session is finalised.
    """

    __tablename__ = "productivity_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("work_sessions.id", ondelete="CASCADE"), nullable=False
    )
    files_per_hour: Mapped[float] = mapped_column(Float, default=0.0)
    commits_per_hour: Mapped[float] = mapped_column(Float, default=0.0)
    lines_added: Mapped[int] = mapped_column(Integer, default=0)
    lines_removed: Mapped[int] = mapped_column(Integer, default=0)
    most_edited_file: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    primary_language: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    session: Mapped["WorkSession"] = relationship(
        "WorkSession", back_populates="metrics"
    )

    def __repr__(self) -> str:
        return f"<ProductivityMetric session={self.session_id} fph={self.files_per_hour:.1f}>"


# ─────────────────────────────────────────────────────────────
# AIGenerationLog
# ─────────────────────────────────────────────────────────────

class AIGenerationLog(Base):
    """
    Audit log for every call made to an AI provider.
    Enables cost estimation, latency tracking, and debugging.
    """

    __tablename__ = "ai_generation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    task: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g. "commit_message"
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<AIGenerationLog provider={self.provider!r} task={self.task!r} ok={self.success}>"
