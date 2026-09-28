# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Layering invariant: ``mycad.core`` and ``mycad`` itself must not import
build123d / OCP / numpy.

Phase 0 keeps the core domain neutral. Only modules under
``mycad.geom`` (introduced in a later wave) and ``mycad.app`` are allowed
to pull CAD backends. The test below also enforces that all
``# type: ignore`` and ``# pyright: ignore`` comments in the repo live
under ``tests/typing/`` — a directory that does not yet exist, so the
current expectation is zero such sites.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

FORBIDDEN_MODULES: frozenset[str] = frozenset({"build123d", "OCP", "numpy"})

ALLOWED_IMPORT_PREFIXES: tuple[str, ...] = (
    "mycad.geom",
    "mycad.app",
)

ALLOWED_IMPORT_FILES: frozenset[str] = frozenset()


def _imported_module_names(node: ast.Import | ast.ImportFrom) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    return [node.module or ""]


def _is_forbidden_in(file_path: Path, module_name: str) -> bool:
    rel = file_path.relative_to(REPO).as_posix()
    # Tests, scripts, and __init__ files are exempted from the layering
    # constraint — they may mention backend names in passing (e.g. an
    # import-leak reverse-self-test).
    if rel.startswith("tests/") or rel.startswith("scripts/"):
        return False
    if rel.endswith("__init__.py"):
        return False
    if rel in ALLOWED_IMPORT_FILES:
        return False
    if module_name.startswith(ALLOWED_IMPORT_PREFIXES):
        return False
    return any(module_name == m or module_name.startswith(m + ".") for m in FORBIDDEN_MODULES)


def test_src_has_no_backend_imports() -> None:
    src = REPO / "src" / "mycad"
    assert src.exists(), "src/mycad missing"
    offenders: list[tuple[str, str]] = []
    for path in sorted(src.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import | ast.ImportFrom):
                for name in _imported_module_names(node):
                    if _is_forbidden_in(path, name):
                        offenders.append((path.relative_to(REPO).as_posix(), name))
    assert not offenders, f"forbidden backend imports in src/: {offenders}"


def test_no_type_ignore_or_pyright_ignore_sites() -> None:
    """T1 invariant: zero suppression comments. ``tests/typing/`` whitelist
    is created in T6; until then any ``# type: ignore`` or
    ``# pyright: ignore`` site must be removed."""

    suffixes = ("py",)
    needles = ("# type: ignore", "# pyright: ignore", "# pyright:")
    offenders: list[str] = []
    for path in REPO.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in suffixes:
            continue
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(REPO).as_posix()
        if rel.startswith("tests/typing/"):
            # Whitelist — created in T6.
            continue
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            for needle in needles:
                if needle in line:
                    offenders.append(f"{rel}:{line_no}: {line.strip()}")
    assert not offenders, "suppression comments detected outside tests/typing/: " + "\n".join(
        offenders
    )
