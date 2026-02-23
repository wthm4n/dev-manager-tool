"""
utils/background_tasks.py
-------------------------
Long-running background tasks started alongside FastAPI.
Currently handles:
  1. Idle session sweeping
  2. Future: metrics aggregation, cleanup jobs
"""

from __future__ import annotations

import asyncio

from config.logging_config import get_logger
from config.settings import Settings
from database.base import AsyncSessionLocal
from services.productivity_service import ProductivityService

logger = get_logger(__name__)


async def sweep_idle_sessions_task(
    productivity: ProductivityService,
    settings: Settings,
) -> None:
    """
    Runs in the background, periodically closing sessions that have been idle
    longer than SESSION_IDLE_TIMEOUT_MINUTES.
    """
    interval = settings.metrics_flush_interval_seconds
    logger.info("Idle session sweeper started", extra={"interval_s": interval})

    while True:
        try:
            await asyncio.sleep(interval)
            async with AsyncSessionLocal() as db:
                closed = await productivity.sweep_idle_sessions(db)
                await db.commit()
                if closed:
                    logger.info(
                        "Idle sessions closed",
                        extra={"count": len(closed), "session_ids": closed},
                    )
        except asyncio.CancelledError:
            logger.info("Idle session sweeper cancelled")
            break
        except Exception as exc:
            logger.error(
                "Error in idle session sweeper",
                extra={"error": str(exc)},
                exc_info=True,
            )
            # Don't crash — wait for next cycle
