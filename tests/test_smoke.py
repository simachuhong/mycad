# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Smoke test — package importable and version pinned."""

from __future__ import annotations


def test_version_is_pinned() -> None:
    """Phase 0 must report exactly '0.1.0'; downstream evidence keys off this."""

    import mycad

    assert mycad.__version__ == "0.1.0"


def test_submodule_core_imports() -> None:
    """core.exceptions, core.geometry_types, core.selectors are importable."""

    from mycad.core import exceptions, geometry_types, selectors  # noqa: F401

    assert exceptions.MycadError is not None
    assert geometry_types.Tessellation is not None
    assert selectors.FaceSelector is not None
