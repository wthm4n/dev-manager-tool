"""
routers/health.py
-----------------
System health and diagnostics endpoints.
"""

from __future__ import annotations

import platform
from datetime import datetime, timezone

import psutil
from fastapi import APIRouter, Depends, Request

from config.settings import get_settings
from core.dependencies import get_ai_service
from services.ai_service import AIService

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("/", summary="Basic liveness check")
async def health() -> dict:
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/detailed", summary="Detailed system and service status")
async def detailed_health(
    request: Request,
    ai_service: AIService = Depends(get_ai_service),
) -> dict:
    settings = get_settings()
    ai_health = await ai_service.provider_health()

    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "app": {
            "name": settings.app_name,
            "env": settings.app_env.value,
            "debug": settings.debug,
        },
        "system": {
            "platform": platform.system(),
            "python": platform.python_version(),
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "memory": {
                "total_mb": round(mem.total / 1024 / 1024),
                "available_mb": round(mem.available / 1024 / 1024),
                "percent_used": mem.percent,
            },
            "disk": {
                "total_gb": round(disk.total / 1024 / 1024 / 1024, 1),
                "free_gb": round(disk.free / 1024 / 1024 / 1024, 1),
                "percent_used": disk.percent,
            },
        },
        "ai": ai_health,
        "watched_projects": len(request.app.state.watcher_service._handlers),
    }
