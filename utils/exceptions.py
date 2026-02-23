"""
utils/exceptions.py
--------------------
Custom exception types and FastAPI exception handlers.
Register all handlers in main.py via app.add_exception_handler().
"""

from __future__ import annotations

from fastapi import Request, status
from fastapi.responses import JSONResponse


# ─────────────────────────────────────────────────────────────
# Domain exceptions
# ─────────────────────────────────────────────────────────────

class DevManagerError(Exception):
    """Base exception for all DevManager AI domain errors."""
    pass


class ProjectNotFoundError(DevManagerError):
    def __init__(self, project_id: str) -> None:
        super().__init__(f"Project not found: {project_id}")
        self.project_id = project_id


class GitOperationError(DevManagerError):
    """Raised when a git operation fails at the domain level."""
    pass


class AIProviderError(DevManagerError):
    """Raised when an AI provider call fails and there is no fallback."""
    pass


# ─────────────────────────────────────────────────────────────
# FastAPI exception handlers
# ─────────────────────────────────────────────────────────────

async def project_not_found_handler(
    request: Request, exc: ProjectNotFoundError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": str(exc), "project_id": exc.project_id},
    )


async def dev_manager_error_handler(
    request: Request, exc: DevManagerError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": str(exc)},
    )


async def unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Catch-all for unexpected errors. Never expose stack traces in production."""
    from config.logging_config import get_logger
    logger = get_logger("exception_handler")
    logger.error(
        "Unhandled exception",
        extra={"path": request.url.path, "error": str(exc)},
        exc_info=True,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal error occurred. Check server logs."},
    )
