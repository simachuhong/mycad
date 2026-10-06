# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Layering guards for the T8 formats slice (T8b).

Text needles are assembled by concatenation so this file never itself
contains the banned literals it scans for.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
FORMATS_SRC = SRC / "mycad" / "formats"
FORMATS_TESTS = TESTS / "formats"
HELPER = "tests/helpers/step_roundtrip.py"
ENUM_HOME = "src/mycad/formats/base.py"


def _py_files(base: Path) -> list[Path]:
    return sorted(p for p in base.rglob("*.py") if "__pycache__" not in p.parts)


def _rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def test_step_read_api_only_in_helper() -> None:
    """The STEP read API lives in exactly one tests file; never in src."""

    needle = "import" + "_step"
    test_offenders = [_rel(p) for p in _py_files(TESTS) if needle in p.read_text(encoding="utf-8")]
    assert test_offenders == [HELPER]

    src_offenders = [_rel(p) for p in _py_files(SRC) if needle in p.read_text(encoding="utf-8")]
    assert src_offenders == []


def test_formats_src_no_cad_imports() -> None:
    """The formats package imports neither CAD kernels nor ``mycad.geom``."""

    banned_roots = {"build123d", "OCP", "mycad.geom"}
    for path in _py_files(FORMATS_SRC):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".", 1)[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                roots = {(node.module or "").split(".", 1)[0]}
                if node.level > 0 or (node.module or "").startswith("mycad.geom"):
                    roots = {(node.module or "mycad.geom")}
            else:
                continue
            assert not (roots & banned_roots), f"{_rel(path)} imports {roots & banned_roots}"


def test_formats_tests_no_app_symbols() -> None:
    """T8 precedes T7: no composition-root symbols leak into formats tests."""

    banned = ("App" + "Services", "build" + "_app", "new" + "_document")
    for path in _py_files(FORMATS_TESTS):
        text = path.read_text(encoding="utf-8")
        for symbol in banned:
            assert symbol not in text, f"{_rel(path)} references {symbol!r}"


def test_no_editable_features_return_path() -> None:
    """``EDITABLE_FEATURES`` appears only at its enum definition site."""

    needle = "EDITABLE" + "_FEATURES"
    occurrences = [_rel(p) for p in _py_files(SRC) if needle in p.read_text(encoding="utf-8")]
    assert occurrences == [ENUM_HOME]
