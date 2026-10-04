# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Neutral selector descriptor tests."""

from __future__ import annotations

import dataclasses
import subprocess
import sys

import pytest

from mycad.core.selectors import EdgeSelector, FaceSelector


def test_face_selector_field_lock() -> None:
    fields = {f.name for f in dataclasses.fields(FaceSelector)}
    assert fields == {"surface", "axis", "rank"}


def test_edge_selector_field_lock() -> None:
    fields = {f.name for f in dataclasses.fields(EdgeSelector)}
    assert fields == {"parent_faces", "curve"}


def test_no_index_field_on_face_or_edge() -> None:
    """Structural absence — selectors carry no positional data."""

    face_fields = {f.name for f in dataclasses.fields(FaceSelector)}
    edge_fields = {f.name for f in dataclasses.fields(EdgeSelector)}
    assert "index" not in face_fields
    assert "index" not in edge_fields


def test_edge_selector_has_no_rank() -> None:
    edge_fields = {f.name for f in dataclasses.fields(EdgeSelector)}
    assert "rank" not in edge_fields


def test_face_selector_is_frozen() -> None:
    fs = FaceSelector(surface="plane")
    with pytest.raises(dataclasses.FrozenInstanceError):
        fs.surface = "cylinder"  # type: ignore[misc]


def test_selectors_dont_import_cad_backends() -> None:
    """Importing selectors must not transitively load build123d/OCP/numpy.

    The guard runs in a fresh subprocess: a live-process ``sys.modules``
    check would be polluted by modules that other tests legitimately
    import during collection.
    """

    code = (
        "import sys; import mycad.core.selectors; "
        'bad = {"build123d", "OCP", "numpy"} & set(sys.modules); '
        "print(','.join(sorted(bad)))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert not result.stdout.strip(), (
        f"selectors leaked CAD/numpy modules: {result.stdout.strip()!r}; check imports"
    )


def test_edge_selector_allows_empty_parent_faces() -> None:
    """Phase 0 keeps the descriptor permissive; downstream code in later
    waves is responsible for ensuring at least one parent face resolves
    to topology."""

    edge = EdgeSelector(parent_faces=())
    assert edge.parent_faces == ()
