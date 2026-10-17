# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Layering invariant: ``mycad.core`` and ``mycad`` itself must not import
build123d / OCP / numpy.

Only modules under ``mycad.geom`` and ``mycad.app`` may pull CAD
backends. ``mycad.ui`` is numpy-capable but Qt-confined: PySide6 is not
in this file's FORBIDDEN_MODULES (its package-level ban lives in
``tests/test_scope_audit.py``), while the must-never-reach-``mycad.geom``
rule below is enforced here. The test also enforces that every type
suppression comment in the repo lives under ``tests/typing/``.
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

# Only the geom adapter package (any internal module split) may import CAD
# backends in src/ — judged by package boundary, not per-module allow-list.
# numpy additionally feeds the ui package (per-frame tessellation buffers),
# so the slice check below releases exactly numpy there and nothing else.
ALLOWED_SRC_IMPORT_PREFIXES: tuple[str, ...] = ("src/mycad/geom/",)
UI_SRC_ALLOWED_PREFIX = "src/mycad/ui/"
UI_SRC_ALLOWED_ROOTS: frozenset[str] = frozenset({"numpy"})

ALLOWED_IMPORT_FILES: frozenset[str] = frozenset()

# In tests/: tests/geom/, the T8 STEP round-trip helper (the file does not
# exist yet — the entry is the plan's exact whitelist wording), and the
# tests/ui/ set (mirrors the numpy release above; discipline mirrors src).
TESTS_ALLOWED_IMPORT_PREFIXES: tuple[str, ...] = ("tests/geom/", "tests/ui/")
TESTS_ALLOWED_IMPORT_FILES: frozenset[str] = frozenset(
    {
        "tests/helpers/step_roundtrip.py",
    }
)


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
    if rel.startswith(ALLOWED_SRC_IMPORT_PREFIXES):
        return False
    if rel.startswith(UI_SRC_ALLOWED_PREFIX):
        return module_name.partition(".")[0] not in UI_SRC_ALLOWED_ROOTS
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


def test_tests_import_backends_only_in_geom_scope() -> None:
    """Inside tests/, build123d / OCP / numpy may only be imported by
    ``tests/geom/`` and the T8 STEP round-trip helper
    ``tests/helpers/step_roundtrip.py``."""

    tests = REPO / "tests"
    assert tests.exists(), "tests/ missing"
    offenders: list[tuple[str, str]] = []
    for path in sorted(tests.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = path.relative_to(REPO).as_posix()
        if rel.startswith(TESTS_ALLOWED_IMPORT_PREFIXES) or rel in TESTS_ALLOWED_IMPORT_FILES:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import | ast.ImportFrom):
                for name in _imported_module_names(node):
                    is_backend = any(
                        name == m or name.startswith(m + ".") for m in FORBIDDEN_MODULES
                    )
                    if is_backend:
                        offenders.append((rel, name))
    assert not offenders, f"forbidden backend imports in tests/: {offenders}"


#: Assembled from fragments so this file does not match itself — same
#: convention as ``tests/formats/test_guards.py``.
SUPPRESSION_NEEDLES = ("# type" + ": ignore", "# pyright" + ": ignore", "# pyright" + ":")

#: The expect-error corpus is the one legal home for suppressions.
SUPPRESSION_WHITELIST = "tests/typing/"


def scan_suppressions(root: Path, repo: Path) -> tuple[list[str], int]:
    """Suppression sites outside the whitelist, and how many files were read."""
    offenders: list[str] = []
    scanned = 0
    for path in root.rglob("*.py"):
        if not path.is_file() or {"__pycache__", ".venv"} & set(path.parts):
            continue
        rel = path.relative_to(repo).as_posix()
        if rel.startswith(SUPPRESSION_WHITELIST):
            continue
        scanned += 1
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for needle in SUPPRESSION_NEEDLES:
                if needle in line:
                    offenders.append(f"{rel}:{line_no}: {line.strip()}")
    return offenders, scanned


def test_no_type_ignore_or_pyright_ignore_sites() -> None:
    """T1 invariant: zero suppression comments outside ``tests/typing/``."""
    offenders, scanned = scan_suppressions(REPO, REPO)
    # This guard shipped in T1 comparing Path.suffix (".py") to "py", so it
    # skipped every file and passed for eleven waves while the invariant was
    # broken. An empty scan is now a failure, not a silent pass.
    assert scanned > 0, "suppression scan read no files — the guard is vacuous"
    assert not offenders, "suppression comments detected outside tests/typing/: " + "\n".join(
        offenders
    )


def test_no_type_ignore_sites_reverse_self_proof(tmp_path: Path) -> None:
    """Plan: "在 src 放一条 ignore 必须变红" — the absent self-proof is why
    the vacuous version of this guard survived every wave."""
    # Pinned by the plan: widening this is the other way to fake a fix, and
    # the tmp-tree assertions below cannot see it.
    assert SUPPRESSION_WHITELIST == "tests/typing/"
    src = tmp_path / "src" / "mycad"
    src.mkdir(parents=True)
    (src / "leak.py").write_text(f"x: int = 1  {SUPPRESSION_NEEDLES[0]}[assignment]\n", "utf-8")
    whitelisted = tmp_path / SUPPRESSION_WHITELIST
    whitelisted.mkdir(parents=True)
    (whitelisted / "expect_errors.py").write_text(f"y = 1  {SUPPRESSION_NEEDLES[1]}[x]\n", "utf-8")

    offenders, scanned = scan_suppressions(tmp_path, tmp_path)
    assert scanned == 1, "the whitelisted file must be skipped, the src file read"
    assert [o.split(":")[0] for o in offenders] == ["src/mycad/leak.py"]


#: T7c composition-root exception: the single src file outside the adapter
#: package that is allowed to import BOTH the geom adapter package and the
#: core domain package. The backend-import ban above applies to it unchanged.
COMPOSITION_ROOT = "src/mycad/app.py"


def test_composition_root_is_the_geom_core_bridge() -> None:
    """The composition root is the only src-level bridge across the two sides.

    When the composition-root file exists it must import both packages; no
    other src file outside the adapter package may do the same. The file is
    the pinned whitelist exception and nothing else ever joins it.
    """
    src = REPO / "src" / "mycad"
    assert src.exists(), "src/mycad missing"
    bridging: set[str] = set()
    for path in sorted(src.rglob("*.py")):
        rel = path.relative_to(REPO).as_posix()
        if rel.startswith(ALLOWED_SRC_IMPORT_PREFIXES) or rel.endswith("__init__.py"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        second_segments: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import | ast.ImportFrom):
                for name in _imported_module_names(node):
                    parts = name.split(".")
                    if parts[0] == "mycad" and len(parts) >= 2:
                        second_segments.add(parts[1])
        if {"geom", "core"} <= second_segments:
            bridging.add(rel)
    assert bridging <= {COMPOSITION_ROOT}, f"unexpected src-level bridges: {sorted(bridging)}"
    if (REPO / COMPOSITION_ROOT).exists():
        assert COMPOSITION_ROOT in bridging, "composition root must bridge both sides"


def test_ui_package_must_not_import_geom() -> None:
    """The UI renders data; it never drives the CAD kernel. src/mycad/ui/
    is banned from importing ``mycad.geom`` at the package root, so a
    ``from mycad.geom.kernel import`` cannot smuggle a backend in through
    a submodule path. Vacuously green while mycad.ui does not yet exist
    (UI package lands in todo 4 on the same plan) — the surgical-hooked
    reverse case is covered by
    ``tests/test_scope_audit.py::test_ui_imports_are_confined_to_the_ui_package``.
    """
    ui = REPO / "src" / "mycad" / "ui"
    if not ui.is_dir():
        return
    offenders: list[tuple[str, str]] = []
    for path in sorted(ui.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import | ast.ImportFrom):
                for name in _imported_module_names(node):
                    if name == "mycad.geom" or name.startswith("mycad.geom."):
                        offenders.append((path.relative_to(REPO).as_posix(), name))
    assert not offenders, f"mycad.ui must not import mycad.geom: {offenders}"
