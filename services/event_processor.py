"""
services/event_processor.py
----------------------------
Asynchronous event processing pipeline.
Consumes batched FileEvent notifications from WatcherService,
persists them to the DB, updates productivity tracking, and
triggers AI commit generation on a configurable debounce.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from config.logging_config import get_logger
from database.base import AsyncSessionLocal
from models.orm import CommitRecord, FileEvent, Project
from services.ai_service import AIService
from services.git_service import GitService
from services.productivity_service import ProductivityService
from services.watcher_service import WatcherService
from sqlalchemy import select

logger = get_logger(__name__)

# After this many seconds of no new events, auto-commit
_AUTO_COMMIT_DEBOUNCE = 30


class EventProcessor:
    """
    Long-running async task that:
    1. Pulls batches from WatcherService queue.
    2. Persists FileEvent rows.
    3. Notifies ProductivityService.
    4. Schedules AI-powered commits after debounce.
    """

    def __init__(
        self,
        watcher: WatcherService,
        git_service: GitService,
        ai_service: AIService,
        productivity: ProductivityService,
    ) -> None:
        self._watcher = watcher
        self._git = git_service
        self._ai = ai_service
        self._productivity = productivity
        self._commit_timers: dict[str, asyncio.TimerHandle] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ── Main processing loop ──────────────────────────────────

    async def run(self) -> None:
        """
        Infinite loop consuming events from the watcher queue.
        Should be started as an asyncio background task.
        """
        self._loop = asyncio.get_running_loop()
        logger.info("EventProcessor started")

        while True:
            try:
                project_id, batch = await self._watcher.consume_events()
                await self._process_batch(project_id, batch)
            except asyncio.CancelledError:
                logger.info("EventProcessor cancelled — shutting down")
                break
            except Exception as exc:
                logger.error(
                    "Unhandled error in event processor",
                    extra={"error": str(exc)},
                    exc_info=True,
                )
                await asyncio.sleep(1)

    # ── Batch handling ────────────────────────────────────────

    async def _process_batch(self, project_id: str, batch: List[dict]) -> None:
        """
        Persist events, update session, schedule auto-commit.
        Each batch gets its own DB session.
        """
        async with AsyncSessionLocal() as db:
            try:
                # Verify project exists
                result = await db.execute(
                    select(Project).where(Project.id == project_id)
                )
                project = result.scalar_one_or_none()
                if not project or not project.is_active:
                    logger.debug(
                        "Skipping batch for inactive/unknown project",
                        extra={"project_id": project_id},
                    )
                    return

                # Persist file events
                file_paths = []
                for entry in batch:
                    fe = FileEvent(
                        project_id=project_id,
                        event_type=entry["event_type"],
                        file_path=entry["file_path"],
                        relative_path=entry.get("relative_path"),
                        is_directory=entry.get("is_directory", False),
                    )
                    db.add(fe)
                    file_paths.append(entry["file_path"])

                await db.flush()

                # Update productivity session
                await self._productivity.observe_activity(
                    project_id=project_id,
                    file_paths=file_paths,
                    db=db,
                )

                await db.commit()

                # Schedule debounced auto-commit
                self._schedule_commit(project_id, project)

            except Exception as exc:
                await db.rollback()
                logger.error(
                    "Error processing event batch",
                    extra={"project_id": project_id, "error": str(exc)},
                    exc_info=True,
                )

    # ── Auto-commit scheduling ────────────────────────────────

    def _schedule_commit(self, project_id: str, project: Project) -> None:
        """
        Cancel any pending commit timer for this project and start a new one.
        After DEBOUNCE seconds of inactivity, execute the commit.
        """
        if not self._loop:
            return

        existing = self._commit_timers.pop(project_id, None)
        if existing:
            existing.cancel()

        handle = self._loop.call_later(
            _AUTO_COMMIT_DEBOUNCE,
            lambda: asyncio.ensure_future(
                self._execute_commit(project_id, project.path, project.project_type),
                loop=self._loop,
            ),
        )
        self._commit_timers[project_id] = handle

    async def _execute_commit(
        self, project_id: str, project_path: str, project_type: str
    ) -> None:
        """
        Collect the diff, generate a commit message via AI, and commit.
        """
        path = Path(project_path)

        # Run sync git operations in thread pool
        diff_stats = await asyncio.to_thread(
            self._git.get_diff_stats, path
        )

        if diff_stats.files_changed == 0:
            logger.debug(
                "Auto-commit skipped — nothing to commit",
                extra={"project_id": project_id},
            )
            return

        async with AsyncSessionLocal() as db:
            try:
                from models.orm import ProjectType
                pt = ProjectType(project_type) if project_type else ProjectType.UNKNOWN

                message = await self._ai.generate_commit_message(
                    diff_stats=diff_stats,
                    project_type=pt,
                    db=db,
                )

                commit_result = await asyncio.to_thread(
                    self._git.commit, path, message
                )

                if commit_result.success:
                    stats = commit_result.stats
                    record = CommitRecord(
                        project_id=project_id,
                        sha=commit_result.sha,
                        message=message,
                        diff_summary=stats.diff_text[:2000] if stats else None,
                        files_changed=stats.files_changed if stats else 0,
                        insertions=stats.insertions if stats else 0,
                        deletions=stats.deletions if stats else 0,
                        ai_provider_used=self._ai._provider.provider_name,
                    )
                    db.add(record)

                    # Mark file events as committed
                    from sqlalchemy import update
                    await db.execute(
                        update(FileEvent)
                        .where(
                            FileEvent.project_id == project_id,
                            FileEvent.committed == False,
                        )
                        .values(committed=True)
                    )
                    await db.commit()

                    logger.info(
                        "Auto-commit successful",
                        extra={
                            "project_id": project_id,
                            "sha": commit_result.sha[:8] if commit_result.sha else None,
                            "message": message[:60],
                        },
                    )
                else:
                    logger.warning(
                        "Auto-commit failed",
                        extra={"project_id": project_id, "error": commit_result.error},
                    )
                    await db.rollback()

            except Exception as exc:
                await db.rollback()
                logger.error(
                    "Exception during auto-commit",
                    extra={"project_id": project_id, "error": str(exc)},
                    exc_info=True,
                )
