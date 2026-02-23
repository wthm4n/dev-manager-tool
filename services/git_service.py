"""
services/git_service.py
-----------------------
Encapsulates all interactions with git via GitPython.
Responsibilities:
  - Initialise repositories
  - Stage and commit changes
  - Read diffs for AI summarisation
  - Return structured stats (files changed, insertions, deletions)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import git
from git import InvalidGitRepositoryError, NoSuchPathError, Repo

from config.logging_config import get_logger
from config.settings import Settings

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────

@dataclass
class DiffStats:
    """Summary statistics from a git diff."""
    files_changed: int = 0
    insertions: int = 0
    deletions: int = 0
    diff_text: str = ""
    changed_files: List[str] = field(default_factory=list)


@dataclass
class CommitResult:
    """Result of a commit operation."""
    success: bool
    sha: Optional[str] = None
    message: str = ""
    error: Optional[str] = None
    stats: Optional[DiffStats] = None


# ─────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────

class GitService:
    """
    All git operations are centralised here.
    Methods are synchronous (GitPython is sync) — wrap in asyncio.to_thread
    when calling from async contexts.
    """

    def __init__(self, settings: Settings) -> None:
        self._author_name = settings.git_author_name
        self._author_email = settings.git_author_email

    # ── Repository management ─────────────────────────────────

    def get_repo(self, path: Path) -> Optional[Repo]:
        """
        Return a Repo object for the given path, or None if it's not a
        git repository.
        """
        try:
            return Repo(str(path), search_parent_directories=True)
        except (InvalidGitRepositoryError, NoSuchPathError):
            return None

    def is_git_repo(self, path: Path) -> bool:
        """Return True if the path is inside a git repository."""
        return self.get_repo(path) is not None

    def init_repo(self, path: Path) -> Tuple[bool, Optional[str]]:
        """
        Initialise a new git repository at path.

        Returns:
            (success, error_message)
        """
        try:
            repo = git.Repo.init(str(path))
            logger.info("Initialised git repo", extra={"path": str(path)})
            # Create an initial .gitignore if none exists
            gitignore = path / ".gitignore"
            if not gitignore.exists():
                gitignore.write_text(self._default_gitignore(), encoding="utf-8")
                repo.index.add([".gitignore"])
                actor = git.Actor(self._author_name, self._author_email)
                repo.index.commit(
                    "chore: initial commit (DevManager AI)",
                    author=actor,
                    committer=actor,
                )
                logger.info("Created initial commit with .gitignore")
            return True, None
        except Exception as exc:
            error = f"Failed to init repo at {path}: {exc}"
            logger.error(error)
            return False, error

    # ── Diff & staging ────────────────────────────────────────

    def get_diff_stats(self, path: Path, staged_only: bool = False) -> DiffStats:
        """
        Return diff statistics for uncommitted changes.

        Args:
            path:        Project root.
            staged_only: If True, only look at staged (index) changes.
        """
        repo = self.get_repo(path)
        if not repo:
            return DiffStats()

        try:
            # Stage all changes so we get a meaningful diff
            if not staged_only:
                repo.git.add(A=True)

            # Get the diff against HEAD (or empty tree if no commits yet)
            if repo.head.is_valid():
                diff = repo.head.commit.diff("HEAD", create_patch=True)
                # Also include untracked vs index
                index_diff = repo.index.diff("HEAD", create_patch=True)
            else:
                # No commits yet — diff against empty tree
                index_diff = repo.index.diff(
                    git.NULL_TREE, create_patch=True
                )
                diff = []

            all_diffs = list(index_diff) + list(diff)

            changed_files: List[str] = []
            diff_chunks: List[str] = []
            insertions = 0
            deletions = 0

            for d in all_diffs:
                try:
                    patch = d.diff.decode("utf-8", errors="replace") if d.diff else ""
                    diff_chunks.append(patch)
                    for line in patch.split("\n"):
                        if line.startswith("+") and not line.startswith("+++"):
                            insertions += 1
                        elif line.startswith("-") and not line.startswith("---"):
                            deletions += 1
                    f = d.b_path or d.a_path
                    if f and f not in changed_files:
                        changed_files.append(f)
                except Exception:
                    continue

            # Also grab untracked files
            untracked = repo.untracked_files
            for f in untracked:
                if f not in changed_files:
                    changed_files.append(f)

            full_diff = "\n".join(diff_chunks)
            # Truncate extremely large diffs to prevent huge LLM prompts
            if len(full_diff) > 8000:
                full_diff = full_diff[:8000] + "\n... (truncated)"

            return DiffStats(
                files_changed=len(changed_files),
                insertions=insertions,
                deletions=deletions,
                diff_text=full_diff,
                changed_files=changed_files,
            )

        except Exception as exc:
            logger.error("Error getting diff stats", extra={"error": str(exc)})
            return DiffStats()

    def stage_all(self, path: Path) -> bool:
        """Stage all changes (git add -A). Returns True on success."""
        repo = self.get_repo(path)
        if not repo:
            return False
        try:
            repo.git.add(A=True)
            return True
        except Exception as exc:
            logger.error("Stage all failed", extra={"error": str(exc)})
            return False

    # ── Commit ────────────────────────────────────────────────

    def commit(self, path: Path, message: str) -> CommitResult:
        """
        Stage all changes and commit with the provided message.
        Returns a CommitResult with the new SHA and diff stats.
        """
        repo = self.get_repo(path)
        if not repo:
            return CommitResult(
                success=False, error="Not a git repository"
            )

        try:
            stats = self.get_diff_stats(path)
            if stats.files_changed == 0 and not repo.untracked_files:
                return CommitResult(
                    success=False,
                    error="Nothing to commit",
                    stats=stats,
                )

            repo.git.add(A=True)
            actor = git.Actor(self._author_name, self._author_email)

            # Preserve any existing GIT_AUTHOR env vars (for passthrough)
            env_overrides = {
                "GIT_AUTHOR_NAME": self._author_name,
                "GIT_AUTHOR_EMAIL": self._author_email,
                "GIT_COMMITTER_NAME": self._author_name,
                "GIT_COMMITTER_EMAIL": self._author_email,
            }
            commit = repo.index.commit(
                message,
                author=actor,
                committer=actor,
            )

            logger.info(
                "Committed",
                extra={"sha": commit.hexsha[:8], "files": stats.files_changed},
            )
            return CommitResult(
                success=True,
                sha=commit.hexsha,
                message=message,
                stats=stats,
            )

        except Exception as exc:
            error = f"Commit failed: {exc}"
            logger.error(error)
            return CommitResult(success=False, error=error)

    # ── Remote info ───────────────────────────────────────────

    def get_remote_url(self, path: Path) -> Optional[str]:
        """Return the URL of the 'origin' remote, or None."""
        repo = self.get_repo(path)
        if not repo:
            return None
        try:
            return repo.remotes.origin.url
        except AttributeError:
            return None

    # ── Helpers ───────────────────────────────────────────────

    @staticmethod
    def _default_gitignore() -> str:
        return """\
# DevManager AI — default .gitignore
__pycache__/
*.py[cod]
*.pyo
.venv/
venv/
env/
node_modules/
dist/
build/
.next/
.DS_Store
*.log
.env
.env.local
*.sqlite
*.db
"""
