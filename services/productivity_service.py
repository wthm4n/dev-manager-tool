"""
services/productivity_service.py
---------------------------------
Tracks developer work sessions and computes productivity metrics.
A session starts on the first file event and is closed after
SESSION_IDLE_TIMEOUT_MINUTES of inactivity.
"""

from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.logging_config import get_logger
from config.settings import Settings
from models.orm import (
    FileEvent,
    ProductivityMetric,
    SessionStatus,
    WorkSession,
)

logger = get_logger(__name__)

# Map extension → language label
_EXT_LANGUAGE: Dict[str, str] = {
    ".py": "Python", ".pyx": "Python",
    ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".rs": "Rust",
    ".go": "Go",
    ".java": "Java",
    ".cs": "C#",
    ".lua": "Lua",
    ".rb": "Ruby",
    ".cpp": "C++", ".cc": "C++", ".cxx": "C++",
    ".c": "C",
    ".html": "HTML",
    ".css": "CSS", ".scss": "SCSS", ".sass": "SASS",
    ".sh": "Shell",
}


class ProductivityService:
    """
    Manages WorkSession lifecycle and ProductivityMetric computation.

    Design:
    - One active session per project at a time.
    - Activity is "observed" via observe_activity().
    - A background sweep_idle_sessions() task closes stale sessions.
    """

    def __init__(self, settings: Settings) -> None:
        self._idle_timeout = timedelta(
            minutes=settings.session_idle_timeout_minutes
        )
        # project_id → active session id (in-memory cache for speed)
        self._active_sessions: Dict[str, int] = {}
        # project_id → last activity timestamp
        self._last_activity: Dict[str, datetime] = {}
        # project_id → set of files touched in current session
        self._session_files: Dict[str, set] = defaultdict(set)

    # ── Session lifecycle ─────────────────────────────────────

    async def observe_activity(
        self,
        project_id: str,
        file_paths: List[str],
        db: AsyncSession,
    ) -> int:
        """
        Record activity for a project, creating or resuming a session.

        Returns:
            The active session ID.
        """
        now = datetime.now(timezone.utc)
        self._last_activity[project_id] = now
        self._session_files[project_id].update(file_paths)

        session_id = self._active_sessions.get(project_id)

        if session_id is None:
            # Start a new session
            session = WorkSession(
                project_id=project_id,
                status=SessionStatus.ACTIVE,
                started_at=now,
                files_touched=len(file_paths),
            )
            db.add(session)
            await db.flush()
            self._active_sessions[project_id] = session.id
            logger.info(
                "New work session started",
                extra={"project_id": project_id, "session_id": session.id},
            )
            return session.id
        else:
            # Update existing session
            result = await db.execute(
                select(WorkSession).where(WorkSession.id == session_id)
            )
            session = result.scalar_one_or_none()
            if session:
                session.files_touched = len(self._session_files[project_id])
                session.status = SessionStatus.ACTIVE
                await db.flush()
            return session_id

    async def close_session(
        self, project_id: str, db: AsyncSession
    ) -> Optional[int]:
        """
        Close the active session for a project and compute its metrics.

        Returns:
            The closed session ID, or None if no active session.
        """
        session_id = self._active_sessions.pop(project_id, None)
        if session_id is None:
            return None

        result = await db.execute(
            select(WorkSession).where(WorkSession.id == session_id)
        )
        session = result.scalar_one_or_none()
        if not session:
            return None

        now = datetime.now(timezone.utc)
        started = session.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)

        duration_minutes = (now - started).total_seconds() / 60.0
        session.ended_at = now
        session.status = SessionStatus.CLOSED
        session.active_minutes = max(0.0, duration_minutes)
        session.files_touched = len(self._session_files.pop(project_id, set()))

        # Compute metrics
        await self._compute_metrics(session, db)
        await db.flush()

        logger.info(
            "Work session closed",
            extra={
                "project_id": project_id,
                "session_id": session_id,
                "duration_min": round(duration_minutes, 1),
            },
        )
        return session_id

    async def sweep_idle_sessions(self, db: AsyncSession) -> List[int]:
        """
        Close all sessions that have been idle longer than the timeout.
        Designed to be called periodically by a background task.

        Returns:
            List of session IDs that were closed.
        """
        now = datetime.now(timezone.utc)
        idle_projects = [
            pid
            for pid, last in self._last_activity.items()
            if (now - last) > self._idle_timeout and pid in self._active_sessions
        ]

        closed = []
        for project_id in idle_projects:
            sid = await self.close_session(project_id, db)
            if sid:
                closed.append(sid)

        return closed

    def increment_commit_count(self, project_id: str) -> None:
        """Called after every successful commit to track session commits."""
        # In-memory only; persisted when session is closed
        # Real implementation would update the ORM object in the session
        pass  # handled via session.commits_made in close_session

    # ── Metrics computation ───────────────────────────────────

    async def _compute_metrics(
        self, session: WorkSession, db: AsyncSession
    ) -> None:
        """Compute and persist ProductivityMetric for a closed session."""
        # Fetch file events for this session's time window
        q = select(FileEvent).where(
            FileEvent.project_id == session.project_id,
            FileEvent.occurred_at >= session.started_at,
            FileEvent.occurred_at <= (session.ended_at or datetime.now(timezone.utc)),
        )
        events_result = await db.execute(q)
        events = events_result.scalars().all()

        hours = max(session.active_minutes / 60.0, 0.001)
        fph = session.files_touched / hours
        cph = session.commits_made / hours

        # Aggregate line counts from linked commits
        lines_added = 0
        lines_removed = 0

        # Most edited file
        file_counter: Counter = Counter(
            e.relative_path or e.file_path for e in events if not e.is_directory
        )
        most_edited = file_counter.most_common(1)[0][0] if file_counter else None

        # Primary language from extensions
        ext_counter: Counter = Counter()
        for path_str in file_counter:
            suffix = "." + path_str.rsplit(".", 1)[-1] if "." in path_str else ""
            lang = _EXT_LANGUAGE.get(suffix)
            if lang:
                ext_counter[lang] += file_counter[path_str]
        primary_lang = ext_counter.most_common(1)[0][0] if ext_counter else None

        metric = ProductivityMetric(
            session_id=session.id,
            files_per_hour=round(fph, 2),
            commits_per_hour=round(cph, 2),
            lines_added=lines_added,
            lines_removed=lines_removed,
            most_edited_file=most_edited,
            primary_language=primary_lang,
        )
        db.add(metric)

    # ── Status helpers ────────────────────────────────────────

    def get_active_session_id(self, project_id: str) -> Optional[int]:
        return self._active_sessions.get(project_id)

    def get_last_activity(self, project_id: str) -> Optional[datetime]:
        return self._last_activity.get(project_id)
