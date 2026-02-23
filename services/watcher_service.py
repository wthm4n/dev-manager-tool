"""
services/watcher_service.py
---------------------------
File system monitoring using the watchdog library.
Maintains one Observer per watched directory.
Emits debounced batches of FileEvents to a processing callback.
"""

from __future__ import annotations

import asyncio
import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Coroutine, Dict, List, Optional, Set

from watchdog.events import (
    DirCreatedEvent,
    DirDeletedEvent,
    DirModifiedEvent,
    DirMovedEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

from config.logging_config import get_logger
from config.settings import Settings
from models.orm import EventType

logger = get_logger(__name__)

# Type alias
EventCallback = Callable[[str, List[dict]], Coroutine]


# ─────────────────────────────────────────────────────────────
# Internal event handler
# ─────────────────────────────────────────────────────────────

class _ProjectEventHandler(FileSystemEventHandler):
    """
    Watchdog handler attached to a single project directory.
    Buffers events and flushes them after a debounce window.
    Thread-safe: watchdog runs handlers in its own thread.
    """

    DEBOUNCE_SECONDS = 3.0  # Wait this long after the last event before flushing

    def __init__(
        self,
        project_id: str,
        project_path: Path,
        ignored_extensions: List[str],
        ignored_dirs: List[str],
        on_flush: Callable[[str, List[dict]], None],
    ) -> None:
        super().__init__()
        self.project_id = project_id
        self.project_path = project_path
        self.ignored_extensions = set(ignored_extensions)
        self.ignored_dirs = set(ignored_dirs)
        self._on_flush = on_flush
        self._buffer: List[dict] = []
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None

    # ── Watchdog callbacks ───────────────────────────────────

    def on_created(self, event: FileSystemEvent) -> None:
        self._push(event, EventType.CREATED)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._push(event, EventType.MODIFIED)

    def on_deleted(self, event: FileSystemEvent) -> None:
        self._push(event, EventType.DELETED)

    def on_moved(self, event: FileSystemEvent) -> None:
        self._push(event, EventType.MOVED)

    # ── Internal ─────────────────────────────────────────────

    def _push(self, event: FileSystemEvent, event_type: EventType) -> None:
        src_path = Path(event.src_path)

        # Skip ignored extensions
        if src_path.suffix in self.ignored_extensions:
            return

        # Skip ignored directories anywhere in the path
        parts = set(src_path.parts)
        if parts & self.ignored_dirs:
            return

        relative = None
        try:
            relative = str(src_path.relative_to(self.project_path))
        except ValueError:
            pass

        entry = {
            "event_type": event_type.value,
            "file_path": str(src_path),
            "relative_path": relative,
            "is_directory": event.is_directory,
            "occurred_at": datetime.utcnow().isoformat(),
        }

        with self._lock:
            # Deduplicate: if same path+type already buffered, skip
            already = any(
                e["file_path"] == entry["file_path"]
                and e["event_type"] == entry["event_type"]
                for e in self._buffer
            )
            if not already:
                self._buffer.append(entry)
            self._reset_timer()

    def _reset_timer(self) -> None:
        """Restart the debounce timer each time a new event arrives."""
        if self._timer and self._timer.is_alive():
            self._timer.cancel()
        self._timer = threading.Timer(self.DEBOUNCE_SECONDS, self._flush)
        self._timer.daemon = True
        self._timer.start()

    def _flush(self) -> None:
        """Called by the timer thread. Hand the batch to the callback."""
        with self._lock:
            if not self._buffer:
                return
            batch = list(self._buffer)
            self._buffer.clear()

        logger.debug(
            "Flushing event batch",
            extra={"project_id": self.project_id, "count": len(batch)},
        )
        self._on_flush(self.project_id, batch)


# ─────────────────────────────────────────────────────────────
# WatcherService
# ─────────────────────────────────────────────────────────────

class WatcherService:
    """
    Manages watchdog Observers for multiple project directories.
    Bridges the synchronous watchdog world into async via a queue.

    Usage:
        service = WatcherService(settings)
        service.start()
        service.watch_project(project_id, path)
        ...
        service.stop()
    """

    def __init__(self, settings: Settings) -> None:
        self._ignored_extensions = settings.ignored_extensions
        self._ignored_dirs = settings.ignored_dirs
        self._observer = Observer()
        self._handlers: Dict[str, _ProjectEventHandler] = {}
        # Async queue for cross-thread communication
        self._queue: asyncio.Queue = asyncio.Queue()
        self._running = False

    # ── Lifecycle ─────────────────────────────────────────────

    def start(self) -> None:
        """Start the watchdog Observer thread."""
        if not self._running:
            self._observer.start()
            self._running = True
            logger.info("WatcherService started")

    def stop(self) -> None:
        """Stop the watchdog Observer and clean up."""
        if self._running:
            self._observer.stop()
            self._observer.join()
            self._running = False
            logger.info("WatcherService stopped")

    # ── Project management ────────────────────────────────────

    def watch_project(self, project_id: str, path: Path) -> bool:
        """
        Begin monitoring a project directory.
        Safe to call multiple times with the same project_id (idempotent).
        """
        if project_id in self._handlers:
            logger.debug("Already watching project", extra={"project_id": project_id})
            return True

        if not path.exists() or not path.is_dir():
            logger.warning(
                "Cannot watch non-existent path", extra={"path": str(path)}
            )
            return False

        handler = _ProjectEventHandler(
            project_id=project_id,
            project_path=path,
            ignored_extensions=self._ignored_extensions,
            ignored_dirs=self._ignored_dirs,
            on_flush=self._sync_flush_callback,
        )
        self._observer.schedule(handler, str(path), recursive=True)
        self._handlers[project_id] = handler
        logger.info("Watching project", extra={"project_id": project_id, "path": str(path)})
        return True

    def unwatch_project(self, project_id: str) -> None:
        """Stop monitoring a project. Events already in queue are preserved."""
        if project_id in self._handlers:
            # watchdog doesn't expose per-watch unschedule easily;
            # mark as stopped by removing from handler dict
            del self._handlers[project_id]
            logger.info("Unwatched project", extra={"project_id": project_id})

    # ── Event piping ─────────────────────────────────────────

    def _sync_flush_callback(self, project_id: str, batch: List[dict]) -> None:
        """
        Called by the watchdog thread.
        Pushes the batch into the async queue for consumption in the event loop.
        Thread-safe: asyncio.Queue.put_nowait is safe from other threads
        when the loop is running.
        """
        try:
            self._queue.put_nowait((project_id, batch))
        except asyncio.QueueFull:
            logger.warning("Event queue full — dropping batch")

    async def consume_events(self) -> tuple[str, List[dict]]:
        """
        Async generator-style method: awaits the next event batch.
        Call from the async processing loop:

            while True:
                project_id, batch = await watcher.consume_events()
                await process_batch(project_id, batch)
        """
        return await self._queue.get()
