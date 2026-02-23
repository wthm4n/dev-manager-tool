"""
routers/sessions.py
-------------------
FastAPI routes for work sessions and productivity metrics.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencies import get_productivity_service
from database.base import get_db
from models.orm import ProductivityMetric, WorkSession
from models.schemas import ProductivityMetricResponse, WorkSessionResponse
from services.productivity_service import ProductivityService

router = APIRouter(prefix="/sessions", tags=["Sessions & Productivity"])


@router.get(
    "/",
    response_model=List[WorkSessionResponse],
    summary="List work sessions for a project",
)
async def list_sessions(
    project_id: str,
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> List[WorkSessionResponse]:
    result = await db.execute(
        select(WorkSession)
        .where(WorkSession.project_id == project_id)
        .order_by(WorkSession.started_at.desc())
        .limit(limit)
        .offset(offset)
    )
    sessions = result.scalars().all()
    return [WorkSessionResponse.model_validate(s) for s in sessions]


@router.get(
    "/active",
    response_model=Optional[WorkSessionResponse],
    summary="Get the currently active session for a project",
)
async def get_active_session(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    productivity: ProductivityService = Depends(get_productivity_service),
) -> Optional[WorkSessionResponse]:
    session_id = productivity.get_active_session_id(project_id)
    if session_id is None:
        return None
    result = await db.execute(
        select(WorkSession).where(WorkSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        return None
    return WorkSessionResponse.model_validate(session)


@router.post(
    "/{session_id}/close",
    response_model=WorkSessionResponse,
    summary="Manually close an active session",
)
async def close_session(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    productivity: ProductivityService = Depends(get_productivity_service),
) -> WorkSessionResponse:
    result = await db.execute(
        select(WorkSession).where(WorkSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    closed_id = await productivity.close_session(session.project_id, db)
    if closed_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Session is not active or already closed",
        )

    # Re-fetch to get updated values
    await db.refresh(session)
    return WorkSessionResponse.model_validate(session)


@router.get(
    "/{session_id}/metrics",
    response_model=Optional[ProductivityMetricResponse],
    summary="Get productivity metrics for a session",
)
async def get_session_metrics(
    session_id: int,
    db: AsyncSession = Depends(get_db),
) -> Optional[ProductivityMetricResponse]:
    result = await db.execute(
        select(ProductivityMetric).where(ProductivityMetric.session_id == session_id)
    )
    metric = result.scalar_one_or_none()
    if not metric:
        return None
    return ProductivityMetricResponse.model_validate(metric)


@router.get(
    "/metrics/summary",
    summary="Aggregate productivity stats across all sessions for a project",
)
async def metrics_summary(
    project_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(WorkSession).where(
            WorkSession.project_id == project_id,
            WorkSession.status == "closed",
        )
    )
    sessions = result.scalars().all()

    if not sessions:
        return {
            "project_id": project_id,
            "total_sessions": 0,
            "total_active_minutes": 0,
            "total_files_touched": 0,
            "total_commits": 0,
        }

    return {
        "project_id": project_id,
        "total_sessions": len(sessions),
        "total_active_minutes": round(sum(s.active_minutes for s in sessions), 1),
        "total_files_touched": sum(s.files_touched for s in sessions),
        "total_commits": sum(s.commits_made for s in sessions),
        "avg_session_minutes": round(
            sum(s.active_minutes for s in sessions) / len(sessions), 1
        ),
    }
