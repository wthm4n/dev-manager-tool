"""
routers/commits.py
------------------
FastAPI routes for commit operations and history.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.logging_config import get_logger
from core.dependencies import get_ai_service, get_git_service, get_project_service
from database.base import get_db
from models.orm import CommitRecord, Project, ProjectType
from models.schemas import CommitRequest, CommitResponse
from services.ai_service import AIService
from services.git_service import GitService
from services.project_service import ProjectService

logger = get_logger(__name__)
router = APIRouter(prefix="/commits", tags=["Commits"])


@router.post(
    "/",
    response_model=CommitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Trigger an AI-powered commit for a project",
)
async def create_commit(
    data: CommitRequest,
    db: AsyncSession = Depends(get_db),
    project_service: ProjectService = Depends(get_project_service),
    git_service: GitService = Depends(get_git_service),
    ai_service: AIService = Depends(get_ai_service),
) -> CommitResponse:
    """
    Stage all pending changes and commit.
    If message_override is provided, skip AI generation.
    Otherwise, generate a Conventional Commits message from the diff.
    """
    project = await project_service.get_project(data.project_id, db)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    path = Path(project.path)
    project_type = ProjectType(project.project_type)

    # Get diff stats (sync → thread pool)
    diff_stats = await asyncio.to_thread(git_service.get_diff_stats, path)

    if diff_stats.files_changed == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Nothing to commit — working directory is clean",
        )

    # Generate or use override message
    if data.message_override:
        message = data.message_override
    else:
        message = await ai_service.generate_commit_message(
            diff_stats=diff_stats,
            project_type=project_type,
            db=db,
        )

    # Execute commit
    result = await asyncio.to_thread(git_service.commit, path, message)
    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Git commit failed: {result.error}",
        )

    stats = result.stats or diff_stats
    record = CommitRecord(
        project_id=data.project_id,
        sha=result.sha,
        message=message,
        diff_summary=stats.diff_text[:2000] if stats.diff_text else None,
        files_changed=stats.files_changed,
        insertions=stats.insertions,
        deletions=stats.deletions,
        ai_provider_used=ai_service._provider.provider_name,
    )
    db.add(record)
    await db.flush()

    logger.info(
        "Manual commit created",
        extra={"project_id": data.project_id, "sha": result.sha[:8] if result.sha else None},
    )

    return CommitResponse.model_validate(record)


@router.get(
    "/",
    response_model=List[CommitResponse],
    summary="List commits for a project",
)
async def list_commits(
    project_id: str,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> List[CommitResponse]:
    result = await db.execute(
        select(CommitRecord)
        .where(CommitRecord.project_id == project_id)
        .order_by(CommitRecord.committed_at.desc())
        .limit(limit)
        .offset(offset)
    )
    records = result.scalars().all()
    return [CommitResponse.model_validate(r) for r in records]


@router.get(
    "/{commit_id}",
    response_model=CommitResponse,
    summary="Get a specific commit record",
)
async def get_commit(
    commit_id: int,
    db: AsyncSession = Depends(get_db),
) -> CommitResponse:
    result = await db.execute(
        select(CommitRecord).where(CommitRecord.id == commit_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Commit not found")
    return CommitResponse.model_validate(record)
