"""
services/project_service.py
---------------------------
High-level business logic for project management.
Orchestrates: project detection, git init, README generation,
and database persistence.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.logging_config import get_logger
from core.project_detector import detect_project_type
from models.orm import Project, ProjectType
from models.schemas import ProjectCreate
from services.ai_service import AIService
from services.git_service import GitService

logger = get_logger(__name__)


class ProjectService:
    """
    CRUD + initialisation logic for Projects.
    Called from API routers and from the event processor.
    """

    def __init__(self, git_service: GitService, ai_service: AIService) -> None:
        self._git = git_service
        self._ai = ai_service

    # ── Create / register ─────────────────────────────────────

    async def register_project(
        self, data: ProjectCreate, db: AsyncSession
    ) -> Project:
        """
        Register a new directory as a project.
        Detects type, optionally inits git, and generates README.
        """
        path = Path(data.path).resolve()

        if not path.exists() or not path.is_dir():
            raise ValueError(f"Path does not exist or is not a directory: {path}")

        # Idempotent: return existing project if already registered
        existing = await self._get_by_path(str(path), db)
        if existing:
            logger.info("Project already registered", extra={"path": str(path)})
            return existing

        name = data.name or path.name
        project_type = detect_project_type(path)

        # Run git detection + init in thread pool (sync)
        has_git = await asyncio.to_thread(self._git.is_git_repo, path)
        git_remote: Optional[str] = None

        if not has_git:
            logger.info("Initialising git repo", extra={"path": str(path)})
            success, err = await asyncio.to_thread(self._git.init_repo, path)
            if success:
                has_git = True
            else:
                logger.warning("Git init failed", extra={"error": err})
        else:
            git_remote = await asyncio.to_thread(self._git.get_remote_url, path)

        project = Project(
            name=name,
            path=str(path),
            project_type=project_type.value,
            has_git=has_git,
            git_remote=git_remote,
        )
        db.add(project)
        await db.flush()  # Get the ID without committing

        # Generate README if missing
        readme_path = path / "README.md"
        if not readme_path.exists():
            await self._generate_readme(project, path, db)

        logger.info(
            "Project registered",
            extra={"project_id": project.id, "project_name": name, "project_type": project_type.value},
        )
        return project

    async def _generate_readme(
        self, project: Project, path: Path, db: AsyncSession
    ) -> None:
        """Generate and write README.md for a project."""
        try:
            file_list = [f.name for f in path.iterdir()]
            readme_content = await self._ai.generate_readme(
                project_name=project.name,
                project_type=ProjectType(project.project_type),
                file_list=file_list,
                db=db,
            )
            readme_path = path / "README.md"
            readme_path.write_text(readme_content, encoding="utf-8")
            project.readme_generated = True
            logger.info("README.md generated", extra={"project": project.name})
        except Exception as exc:
            logger.warning("README generation failed", extra={"error": str(exc)})

    # ── Read ──────────────────────────────────────────────────

    async def get_project(self, project_id: str, db: AsyncSession) -> Optional[Project]:
        result = await db.execute(select(Project).where(Project.id == project_id))
        return result.scalar_one_or_none()

    async def list_projects(
        self, db: AsyncSession, active_only: bool = True
    ) -> List[Project]:
        q = select(Project)
        if active_only:
            q = q.where(Project.is_active == True)
        result = await db.execute(q)
        return list(result.scalars().all())

    async def _get_by_path(self, path: str, db: AsyncSession) -> Optional[Project]:
        result = await db.execute(select(Project).where(Project.path == path))
        return result.scalar_one_or_none()

    # ── Update ────────────────────────────────────────────────

    async def deactivate_project(
        self, project_id: str, db: AsyncSession
    ) -> Optional[Project]:
        project = await self.get_project(project_id, db)
        if project:
            project.is_active = False
        return project

    async def refresh_project_type(
        self, project_id: str, db: AsyncSession
    ) -> Optional[Project]:
        """Re-run detection and update the stored project type."""
        project = await self.get_project(project_id, db)
        if not project:
            return None
        path = Path(project.path)
        new_type = detect_project_type(path)
        project.project_type = new_type.value
        return project