"""
tests/unit/test_project_detector.py
------------------------------------
Unit tests for the heuristic project type detector.
No database, no I/O side-effects — pure logic testing.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from core.project_detector import detect_project_type, get_primary_language
from models.orm import ProjectType


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Return a fresh temporary directory for each test."""
    return tmp_path


class TestProjectDetection:
    def test_python_pyproject(self, tmp_project: Path) -> None:
        (tmp_project / "pyproject.toml").touch()
        assert detect_project_type(tmp_project) == ProjectType.PYTHON

    def test_python_requirements(self, tmp_project: Path) -> None:
        (tmp_project / "requirements.txt").touch()
        assert detect_project_type(tmp_project) == ProjectType.PYTHON

    def test_rust_cargo(self, tmp_project: Path) -> None:
        (tmp_project / "Cargo.toml").touch()
        assert detect_project_type(tmp_project) == ProjectType.RUST

    def test_go_mod(self, tmp_project: Path) -> None:
        (tmp_project / "go.mod").touch()
        assert detect_project_type(tmp_project) == ProjectType.GO

    def test_nextjs_config(self, tmp_project: Path) -> None:
        (tmp_project / "next.config.js").touch()
        assert detect_project_type(tmp_project) == ProjectType.NEXTJS

    def test_react_vite(self, tmp_project: Path) -> None:
        (tmp_project / "vite.config.ts").touch()
        src = tmp_project / "src"
        src.mkdir()
        (src / "App.tsx").touch()
        assert detect_project_type(tmp_project) == ProjectType.REACT

    def test_roblox_project(self, tmp_project: Path) -> None:
        (tmp_project / "default.project.json").touch()
        assert detect_project_type(tmp_project) == ProjectType.ROBLOX

    def test_unknown_empty_dir(self, tmp_project: Path) -> None:
        assert detect_project_type(tmp_project) == ProjectType.UNKNOWN

    def test_non_existent_path(self) -> None:
        assert detect_project_type(Path("/definitely/does/not/exist")) == ProjectType.UNKNOWN

    def test_nextjs_beats_node(self, tmp_project: Path) -> None:
        """next.config.js should score higher than generic node signals."""
        (tmp_project / "next.config.js").touch()
        (tmp_project / "package.json").touch()
        assert detect_project_type(tmp_project) == ProjectType.NEXTJS


class TestPrimaryLanguage:
    def test_python_language(self) -> None:
        assert get_primary_language(ProjectType.PYTHON) == "Python"

    def test_rust_language(self) -> None:
        assert get_primary_language(ProjectType.RUST) == "Rust"

    def test_unknown_language(self) -> None:
        assert get_primary_language(ProjectType.UNKNOWN) is None
