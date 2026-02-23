"""
core/dependencies.py
--------------------
Dependency Injection container for FastAPI.
All services are instantiated once at startup and stored in app.state.
FastAPI routes receive them via Depends() callbacks defined here.

This pattern avoids global variables while keeping DI clean and testable.
"""

from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import get_db
from providers.base import AIProviderBase
from services.ai_service import AIService
from services.git_service import GitService
from services.productivity_service import ProductivityService
from services.project_service import ProjectService
from services.watcher_service import WatcherService


# ─────────────────────────────────────────────────────────────
# State accessors (read from app.state set in main.py lifespan)
# ─────────────────────────────────────────────────────────────

def get_ai_provider(request: Request) -> AIProviderBase:
    return request.app.state.ai_provider


def get_ai_service(request: Request) -> AIService:
    return request.app.state.ai_service


def get_git_service(request: Request) -> GitService:
    return request.app.state.git_service


def get_watcher_service(request: Request) -> WatcherService:
    return request.app.state.watcher_service


def get_productivity_service(request: Request) -> ProductivityService:
    return request.app.state.productivity_service


def get_project_service(request: Request) -> ProjectService:
    return request.app.state.project_service


# ─────────────────────────────────────────────────────────────
# Convenience: combine DB + service in one Depends
# ─────────────────────────────────────────────────────────────

async def project_service_and_db(
    project_service: ProjectService = Depends(get_project_service),
    db: AsyncSession = Depends(get_db),
) -> tuple[ProjectService, AsyncSession]:
    return project_service, db
