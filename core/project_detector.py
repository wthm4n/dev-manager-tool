"""
core/project_detector.py
------------------------
Heuristic-based project type detection.
Inspects the filesystem (files present) to classify a directory.
Completely stateless — no DB access, no I/O side-effects beyond reading.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from models.orm import ProjectType


# ─────────────────────────────────────────────────────────────
# Detection rules
# Each rule is (indicator_files_or_dirs, weight).
# The type with the highest cumulative weight wins.
# ─────────────────────────────────────────────────────────────

_DETECTION_RULES: Dict[ProjectType, List[Tuple[str, int]]] = {
    ProjectType.NEXTJS: [
        ("next.config.js", 10),
        ("next.config.ts", 10),
        ("next.config.mjs", 10),
        (".next", 8),
        ("app/page.tsx", 6),
        ("pages/_app.tsx", 6),
    ],
    ProjectType.REACT: [
        ("src/App.tsx", 8),
        ("src/App.jsx", 8),
        ("src/index.tsx", 6),
        ("src/index.jsx", 6),
        ("public/index.html", 5),
        ("vite.config.ts", 4),
        ("vite.config.js", 4),
        ("create-react-app", 3),
    ],
    ProjectType.NODE: [
        ("package.json", 4),
        ("node_modules", 3),
        ("index.js", 2),
        ("index.ts", 2),
        ("server.js", 4),
        ("app.js", 3),
        ("tsconfig.json", 2),
    ],
    ProjectType.PYTHON: [
        ("pyproject.toml", 10),
        ("setup.py", 8),
        ("setup.cfg", 8),
        ("requirements.txt", 6),
        ("Pipfile", 6),
        ("poetry.lock", 8),
        ("main.py", 4),
        ("manage.py", 6),   # Django
        ("wsgi.py", 5),
        ("asgi.py", 5),
    ],
    ProjectType.ROBLOX: [
        ("default.project.json", 10),
        (".rojo", 8),
        ("*.rbxl", 8),
        ("*.rbxlx", 8),
        ("src/ServerScriptService", 6),
        ("src/ReplicatedStorage", 6),
    ],
    ProjectType.RUST: [
        ("Cargo.toml", 10),
        ("Cargo.lock", 8),
        ("src/main.rs", 6),
        ("src/lib.rs", 6),
    ],
    ProjectType.GO: [
        ("go.mod", 10),
        ("go.sum", 8),
        ("main.go", 6),
        ("cmd/", 5),
    ],
    ProjectType.JAVA: [
        ("pom.xml", 10),
        ("build.gradle", 10),
        ("build.gradle.kts", 10),
        ("src/main/java", 8),
        ("gradlew", 5),
    ],
    ProjectType.DOTNET: [
        ("*.csproj", 10),
        ("*.sln", 10),
        ("*.fsproj", 10),
        ("Program.cs", 6),
        ("appsettings.json", 5),
    ],
}

# Minimum score to be classified as that type
_MIN_CONFIDENCE = 4


def detect_project_type(path: Path) -> ProjectType:
    """
    Walk the top two levels of a directory and score each possible
    project type based on the presence of indicator files/dirs.

    Returns the highest-scoring type, or UNKNOWN if no type reaches
    the minimum confidence threshold.
    """
    if not path.exists() or not path.is_dir():
        return ProjectType.UNKNOWN

    # Collect names of direct children (one level deep for performance)
    candidates: List[Path] = list(path.iterdir())
    child_names = {c.name for c in candidates}
    # Second level
    for child in candidates:
        if child.is_dir() and child.name not in {".git", "node_modules", "__pycache__"}:
            try:
                child_names.update(c.name for c in child.iterdir())
            except PermissionError:
                continue

    scores: Dict[ProjectType, int] = {pt: 0 for pt in _DETECTION_RULES}

    for project_type, rules in _DETECTION_RULES.items():
        for indicator, weight in rules:
            # Glob-style wildcard (e.g. *.csproj)
            if indicator.startswith("*"):
                ext = indicator[1:]  # e.g. ".csproj"
                if any(n.endswith(ext) for n in child_names):
                    scores[project_type] += weight
            else:
                # Exact name match (file or dir basename)
                target = Path(indicator).name
                if target in child_names:
                    scores[project_type] += weight
                # Full relative path match
                elif (path / indicator).exists():
                    scores[project_type] += weight

    best_type = max(scores, key=lambda t: scores[t])
    if scores[best_type] >= _MIN_CONFIDENCE:
        return best_type

    return ProjectType.UNKNOWN


def get_primary_language(project_type: ProjectType) -> Optional[str]:
    """Return a human-readable language string for a project type."""
    _MAP = {
        ProjectType.REACT: "TypeScript/JavaScript",
        ProjectType.NEXTJS: "TypeScript/JavaScript",
        ProjectType.NODE: "JavaScript/TypeScript",
        ProjectType.PYTHON: "Python",
        ProjectType.ROBLOX: "Lua/Luau",
        ProjectType.RUST: "Rust",
        ProjectType.GO: "Go",
        ProjectType.JAVA: "Java",
        ProjectType.DOTNET: "C#",
    }
    return _MAP.get(project_type)
