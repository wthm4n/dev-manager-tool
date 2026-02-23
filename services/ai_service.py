"""
services/ai_service.py
----------------------
High-level AI operations for DevManager AI.
This service owns all prompt engineering.
It depends on AIProviderBase — never on a concrete provider.
All calls are logged to the AIGenerationLog table.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from config.logging_config import get_logger
from models.orm import AIGenerationLog, ProjectType
from providers.base import AIProviderBase, GenerationResult
from services.git_service import DiffStats

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────────
# Prompt templates
# ─────────────────────────────────────────────────────────────

_COMMIT_SYSTEM = """\
You are a senior software engineer writing git commit messages.
Follow the Conventional Commits specification strictly.
Format: <type>(<optional scope>): <short description>

Types: feat, fix, refactor, style, test, docs, chore, perf, build, ci
Rules:
- First line MUST be under 72 characters
- Use imperative mood ("add" not "added")
- No period at the end of the subject line
- If needed, add a blank line then a body with more detail
- Output ONLY the commit message, no explanation or preamble
"""

_README_SYSTEM = """\
You are a technical writer creating professional README.md files for developers.
Write clear, concise, actionable documentation.
Use standard markdown. Include: project title, description, tech stack,
installation, usage, and contributing sections.
Output ONLY valid markdown. No commentary outside the markdown.
"""


class AIService:
    """
    Business-logic layer for all AI generation tasks.
    Persists audit records to AIGenerationLog after every call.
    """

    def __init__(self, provider: AIProviderBase) -> None:
        self._provider = provider

    # ── Commit message generation ─────────────────────────────

    async def generate_commit_message(
        self,
        diff_stats: DiffStats,
        project_type: ProjectType,
        db: Optional[AsyncSession] = None,
    ) -> str:
        """
        Generate a Conventional Commits message from a diff.

        Args:
            diff_stats:   Statistics and raw diff text.
            project_type: Helps the model produce contextual scopes.
            db:           Optional session for audit logging.

        Returns:
            Commit message string. Falls back to a generic message on failure.
        """
        files_list = "\n".join(f"  - {f}" for f in diff_stats.changed_files[:30])
        prompt = f"""\
Project type: {project_type.value}
Files changed ({diff_stats.files_changed}):
{files_list}

Insertions: {diff_stats.insertions}  Deletions: {diff_stats.deletions}

Diff (may be truncated):
```diff
{diff_stats.diff_text}
```

Write a conventional commit message for these changes."""

        result = await self._provider.generate(
            prompt=prompt,
            system_prompt=_COMMIT_SYSTEM,
            max_tokens=256,
            temperature=0.2,
        )

        await self._log(result, task="commit_message", db=db)

        if result.success and result.text:
            # Take only the first non-empty line as the commit subject
            lines = [l.strip() for l in result.text.strip().splitlines() if l.strip()]
            return "\n".join(lines) if lines else self._fallback_commit(diff_stats)

        return self._fallback_commit(diff_stats)

    # ── README generation ─────────────────────────────────────

    async def generate_readme(
        self,
        project_name: str,
        project_type: ProjectType,
        file_list: list[str],
        db: Optional[AsyncSession] = None,
    ) -> str:
        """
        Generate a README.md for a project.

        Args:
            project_name: Directory / display name.
            project_type: Detected project type.
            file_list:    Top-level files/dirs (for context).
            db:           Optional session for audit logging.

        Returns:
            Markdown string for README.md content.
        """
        files_str = "\n".join(f"  - {f}" for f in file_list[:40])
        prompt = f"""\
Project name: {project_name}
Project type: {project_type.value}
Top-level contents:
{files_str}

Generate a professional README.md for this project.
Make reasonable assumptions based on the project type.
"""

        result = await self._provider.generate(
            prompt=prompt,
            system_prompt=_README_SYSTEM,
            max_tokens=1500,
            temperature=0.4,
        )

        await self._log(result, task="readme_generation", db=db)

        if result.success and result.text:
            return result.text

        return self._fallback_readme(project_name, project_type)

    # ── Health ────────────────────────────────────────────────

    async def provider_health(self) -> dict:
        """Return a health status dict for the active AI provider."""
        healthy = await self._provider.health_check()
        return {
            "provider": self._provider.provider_name,
            "model": self._provider.model_name,
            "healthy": healthy,
        }

    # ── Audit logging ─────────────────────────────────────────

    async def _log(
        self,
        result: GenerationResult,
        task: str,
        db: Optional[AsyncSession],
    ) -> None:
        """Persist an AIGenerationLog row (best-effort — never raises)."""
        if db is None:
            return
        try:
            log_entry = AIGenerationLog(
                provider=result.provider,
                model=result.model,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                latency_ms=result.latency_ms,
                task=task,
                success=result.success,
                error_message=result.error,
            )
            db.add(log_entry)
            await db.flush()
        except Exception as exc:
            logger.warning("Failed to log AI generation", extra={"error": str(exc)})

    # ── Fallbacks ─────────────────────────────────────────────

    @staticmethod
    def _fallback_commit(stats: DiffStats) -> str:
        """Generate a basic commit message when AI is unavailable."""
        n = stats.files_changed
        return f"chore: update {n} file{'s' if n != 1 else ''}"

    @staticmethod
    def _fallback_readme(name: str, project_type: ProjectType) -> str:
        return f"""\
# {name}

> Auto-generated by DevManager AI

## About

A {project_type.value} project.

## Getting Started

_Add setup instructions here._

## Contributing

_Add contribution guidelines here._
"""
