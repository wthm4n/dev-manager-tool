"""
main.py
-------
FastAPI application factory and lifespan manager.

Startup sequence:
  1. Configure logging
  2. Initialize database tables
  3. Instantiate services (DI container)
  4. Register pre-configured projects from WATCHED_PATHS env var
  5. Start WatcherService
  6. Launch background tasks (event processor, session sweeper)

Shutdown sequence:
  1. Cancel background tasks
  2. Stop WatcherService
  3. Close AI provider HTTP client
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.logging_config import configure_logging, get_logger
from config.settings import get_settings
from database.base import AsyncSessionLocal, init_db
from models.orm import Project  # noqa: F401 — ensures metadata is populated
from providers.factory import build_ai_provider
from routers.commits import router as commits_router
from routers.health import router as health_router
from routers.projects import router as projects_router
from routers.sessions import router as sessions_router
from services.ai_service import AIService
from services.event_processor import EventProcessor
from services.git_service import GitService
from services.productivity_service import ProductivityService
from services.project_service import ProjectService
from services.watcher_service import WatcherService
from utils.background_tasks import sweep_idle_sessions_task
from utils.exceptions import (
    DevManagerError,
    ProjectNotFoundError,
    dev_manager_error_handler,
    project_not_found_handler,
    unhandled_exception_handler,
)

# Configure logging before anything else
configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    FastAPI lifespan context manager.
    Everything before `yield` runs on startup; after yield on shutdown.
    """
    settings = get_settings()
    logger.info("DevManager AI starting up", extra={"env": settings.app_env.value})

    # ── Database ─────────────────────────────────────────────
    await init_db()
    logger.info("Database initialised")

    # ── Service instantiation ─────────────────────────────────
    ai_provider = build_ai_provider(settings)
    ai_service = AIService(provider=ai_provider)
    git_service = GitService(settings=settings)
    watcher_service = WatcherService(settings=settings)
    productivity_service = ProductivityService(settings=settings)
    project_service = ProjectService(
        git_service=git_service,
        ai_service=ai_service,
    )

    # Store in app.state for DI
    app.state.ai_provider = ai_provider
    app.state.ai_service = ai_service
    app.state.git_service = git_service
    app.state.watcher_service = watcher_service
    app.state.productivity_service = productivity_service
    app.state.project_service = project_service

    # ── Start file watcher ────────────────────────────────────
    watcher_service.start()

    # ── Register pre-configured watched paths ─────────────────
    if settings.watched_paths:
        async with AsyncSessionLocal() as db:
            for path in settings.watched_paths:
                if path.exists() and path.is_dir():
                    try:
                        from models.schemas import ProjectCreate
                        project = await project_service.register_project(
                            ProjectCreate(path=str(path)), db
                        )
                        watcher_service.watch_project(project.id, path)
                        await db.commit()
                        logger.info(
                            "Auto-registered project from WATCHED_PATHS",
                            extra={"path": str(path), "id": project.id},
                        )
                    except Exception as exc:
                        await db.rollback()
                        logger.warning(
                            "Failed to auto-register path",
                            extra={"path": str(path), "error": str(exc)},
                        )
                else:
                    logger.warning(
                        "WATCHED_PATHS entry does not exist, skipping",
                        extra={"path": str(path)},
                    )

    # ── Background tasks ──────────────────────────────────────
    event_processor = EventProcessor(
        watcher=watcher_service,
        git_service=git_service,
        ai_service=ai_service,
        productivity=productivity_service,
    )
    task_processor = asyncio.create_task(
        event_processor.run(), name="event_processor"
    )
    task_sweeper = asyncio.create_task(
        sweep_idle_sessions_task(productivity_service, settings),
        name="session_sweeper",
    )

    logger.info("DevManager AI ready")

    # ── Hand off to FastAPI ───────────────────────────────────
    yield

    # ── Shutdown ──────────────────────────────────────────────
    logger.info("DevManager AI shutting down")

    task_processor.cancel()
    task_sweeper.cancel()
    await asyncio.gather(task_processor, task_sweeper, return_exceptions=True)

    watcher_service.stop()

    if hasattr(ai_provider, "close"):
        await ai_provider.close()

    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="DevManager AI",
        description=(
            "Local-first AI-powered developer automation tool. "
            "Monitors folders, auto-commits, tracks productivity."
        ),
        version="1.0.0",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # ── CORS ──────────────────────────────────────────────────
    origins = ["http://localhost:3000", "http://localhost:5173"]  # React dev servers
    if settings.is_production:
        origins = []  # Lock down in production — configure explicitly

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Exception handlers ────────────────────────────────────
    app.add_exception_handler(ProjectNotFoundError, project_not_found_handler)
    app.add_exception_handler(DevManagerError, dev_manager_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    # ── Routers ───────────────────────────────────────────────
    app.include_router(health_router)
    app.include_router(projects_router)
    app.include_router(commits_router)
    app.include_router(sessions_router)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.debug,
        log_level=settings.log_level.value.lower(),
    )
