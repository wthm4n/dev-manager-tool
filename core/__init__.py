from core.project_detector import detect_project_type, get_primary_language
from core.dependencies import (
    get_ai_service,
    get_git_service,
    get_watcher_service,
    get_productivity_service,
    get_project_service,
)

__all__ = [
    "detect_project_type", "get_primary_language",
    "get_ai_service", "get_git_service",
    "get_watcher_service", "get_productivity_service", "get_project_service",
]
