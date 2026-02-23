"""
routers/projects.py
-------------------
FastAPI routes for project management.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencies import get_project_service, get_watcher_service
from database.base import get_db
from models.schemas import MessageResponse, ProjectCreate, ProjectResponse, ProjectUpdate
from services.project_service import ProjectService
from services.watcher_service import WatcherService
from pathlib import Path

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.post(
    "/",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new project directory",
)
async def register_project(
    data: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    project_service: ProjectService = Depends(get_project_service),
    watcher: WatcherService = Depends(get_watcher_service),
) -> ProjectResponse:
    """
    Register a directory as a DevManager AI project.

    This will:
    - Detect the project type automatically
    - Initialise a git repo if one doesn't exist
    - Generate README.md if missing
    - Start file monitoring
    """
    try:
        project = await project_service.register_project(data, db)
        # Begin file watching
        watcher.watch_project(project.id, Path(project.path))
        return ProjectResponse.model_validate(project)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get(
    "/",
    response_model=List[ProjectResponse],
    summary="List all registered projects",
)
async def list_projects(
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
    project_service: ProjectService = Depends(get_project_service),
) -> List[ProjectResponse]:
    projects = await project_service.list_projects(db, active_only=active_only)
    return [ProjectResponse.model_validate(p) for p in projects]


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Get project by ID",
)
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    project_service: ProjectService = Depends(get_project_service),
) -> ProjectResponse:
    project = await project_service.get_project(project_id, db)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return ProjectResponse.model_validate(project)


@router.patch(
    "/{project_id}/deactivate",
    response_model=MessageResponse,
    summary="Deactivate a project (stop monitoring)",
)
async def deactivate_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    project_service: ProjectService = Depends(get_project_service),
    watcher: WatcherService = Depends(get_watcher_service),
) -> MessageResponse:
    project = await project_service.deactivate_project(project_id, db)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    watcher.unwatch_project(project_id)
    return MessageResponse(message=f"Project '{project.name}' deactivated")


@router.post(
    "/{project_id}/refresh-type",
    response_model=ProjectResponse,
    summary="Re-detect project type",
)
async def refresh_project_type(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    project_service: ProjectService = Depends(get_project_service),
) -> ProjectResponse:
    project = await project_service.refresh_project_type(project_id, db)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return ProjectResponse.model_validate(project)
