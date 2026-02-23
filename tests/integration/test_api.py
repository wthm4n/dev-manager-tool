"""
tests/integration/test_api.py
------------------------------
Integration tests for FastAPI routes.
Uses an in-memory SQLite database and mock AI provider.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database.base import Base, get_db
from main import create_app
from providers.base import AIProviderBase, GenerationResult


# ─────────────────────────────────────────────────────────────
# Mock AI Provider
# ─────────────────────────────────────────────────────────────

class MockAIProvider(AIProviderBase):
    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return "mock-model"

    async def generate(self, prompt, system_prompt=None, max_tokens=1024, temperature=0.3):
        return GenerationResult(
            text="chore: update files",
            success=True,
            provider="mock",
            model="mock-model",
        )

    async def health_check(self) -> bool:
        return True


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def project_dir(tmp_path_factory) -> Path:
    """A real temporary directory to act as a project."""
    d = tmp_path_factory.mktemp("test_project")
    (d / "requirements.txt").touch()
    (d / "main.py").write_text("print('hello')")
    return d


@pytest.fixture
def app(project_dir):
    """Create a FastAPI app with mocked services."""
    application = create_app()

    mock_provider = MockAIProvider()
    from services.ai_service import AIService
    from services.git_service import GitService
    from services.watcher_service import WatcherService
    from services.productivity_service import ProductivityService
    from services.project_service import ProjectService
    from config.settings import get_settings

    settings = get_settings()
    git_service = GitService(settings=settings)
    ai_service = AIService(provider=mock_provider)
    watcher = MagicMock(spec=WatcherService)
    watcher.watch_project.return_value = True
    productivity = ProductivityService(settings=settings)
    project_service = ProjectService(git_service=git_service, ai_service=ai_service)

    application.state.ai_provider = mock_provider
    application.state.ai_service = ai_service
    application.state.git_service = git_service
    application.state.watcher_service = watcher
    application.state.productivity_service = productivity
    application.state.project_service = project_service

    return application


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ─────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────

class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        response = client.get("/health/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "timestamp" in data


class TestProjectsEndpoint:
    def test_list_projects_empty(self, client):
        response = client.get("/projects/")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_get_nonexistent_project(self, client):
        response = client.get("/projects/nonexistent-id")
        assert response.status_code == 404
