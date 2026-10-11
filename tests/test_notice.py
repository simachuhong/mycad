# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""NOTICE completeness, fail-closed.

The attribution list is compared against the runtime closure measured in
the current environment — never against a list typed into this file. A
distribution that enters the closure without an attribution line fails
here, and so does any placeholder wording.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.test_scope_audit import UV_TREE_COMMAND, parse_closure

REPO = Path(__file__).resolve().parent.parent
NOTICE = (REPO / "NOTICE").read_text(encoding="utf-8")

#: The five components the plan names explicitly. OCCT is attributed
#: through the cadquery-ocp-novtk wheel that bundles it.
MAJOR_COMPONENTS: tuple[str, ...] = (
    "build123d",
    "cadquery-ocp-novtk",
    "numpy",
    "ezdxf",
    "lib3mf",
)

#: Wording that must never reach a shippable NOTICE (fail-closed).
PLACEHOLDERS: tuple[str, ...] = ("待核实", "TBD", "未知", "unknown license", "FIXME")


def test_project_license_is_apache() -> None:
    assert "Apache License, Version 2.0" in NOTICE
    assert "Apache License" in (REPO / "LICENSE").read_text(encoding="utf-8")


def test_major_components_are_attributed() -> None:
    for name in MAJOR_COMPONENTS:
        assert name in NOTICE, f"NOTICE is missing {name}"


def test_occt_has_both_attributions() -> None:
    """The binding code and the bundled native libraries differ in license."""
    assert "Open CASCADE Technology 7.9.3 (bundled)" in NOTICE
    assert "LGPL-2.1" in NOTICE
    assert "Open CASCADE exception" in NOTICE
    # The binding's own measured identifier must still be stated.
    assert "cadquery-ocp-novtk (OCP binding code)   Apache-2.0" in NOTICE


def test_no_placeholder_wording() -> None:
    for placeholder in PLACEHOLDERS:
        assert placeholder not in NOTICE, f"NOTICE still contains {placeholder!r}"


def test_every_runtime_distribution_is_listed() -> None:
    # uv emits UTF-8 regardless of locale; Windows text=True defaults to
    # cp1252 and mojibakes the tree glyphs into the parsed closure.
    result = subprocess.run(
        UV_TREE_COMMAND,
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"uv unavailable: {result.stderr.strip()[:120]}")
    closure = parse_closure(result.stdout) - {"mycad"}
    assert closure, "closure parse produced nothing"
    missing = sorted(name for name in closure if name not in NOTICE.lower())
    assert missing == [], f"NOTICE does not attribute: {missing}"


def test_dev_tools_are_not_in_the_runtime_closure() -> None:
    """The dev dependency group must stay out of the attribution scope."""
    # uv emits UTF-8 regardless of locale; Windows text=True defaults to
    # cp1252 and mojibakes the tree glyphs into the parsed closure.
    result = subprocess.run(
        UV_TREE_COMMAND,
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("uv unavailable")
    closure = parse_closure(result.stdout)
    assert {"ruff", "pytest", "basedpyright", "hatchling"} & closure == set()
