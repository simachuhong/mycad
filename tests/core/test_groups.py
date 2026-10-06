# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""NamedGroup contract tests (#10)."""

from __future__ import annotations

import dataclasses

import pytest

from mycad.core.groups import NamedGroup
from mycad.core.selectors import EdgeSelector, FaceSelector


def _face() -> FaceSelector:
    return FaceSelector(surface="plane", axis="+Z")


def _edge() -> EdgeSelector:
    return EdgeSelector(parent_faces=(_face(),), curve="circle")


def test_named_group_field_lock() -> None:
    fields = {f.name for f in dataclasses.fields(NamedGroup)}
    assert fields == {"name", "faces", "edges"}


def test_named_group_is_frozen() -> None:
    group = NamedGroup(name="top")
    with pytest.raises(dataclasses.FrozenInstanceError):
        group.name = "other"  # type: ignore[misc]


def test_named_group_defaults_empty() -> None:
    group = NamedGroup(name="empty")
    assert group.faces == ()
    assert group.edges == ()


def test_named_group_fields_roundtrip() -> None:
    face = _face()
    edge = _edge()
    group = NamedGroup(name="bolt_holes", faces=(face,), edges=(edge,))
    assert group.name == "bolt_holes"
    assert group.faces == (face,)
    assert group.edges == (edge,)


def test_named_group_list_inputs_become_tuples() -> None:
    faces = [_face(), _face()]
    edges = [_edge()]
    group = NamedGroup(name="from_lists", faces=faces, edges=edges)  # type: ignore[arg-type]
    assert isinstance(group.faces, tuple)
    assert isinstance(group.edges, tuple)
    assert group.faces == tuple(faces)
    assert group.edges == tuple(edges)


def test_named_groups_do_not_import_cad_backends() -> None:
    """Importing groups must not transitively load build123d/OCP/numpy.

    The guard runs in a fresh subprocess: a live-process ``sys.modules``
    check would be polluted by modules that other tests legitimately
    import during collection (e.g. test_ports imports the real BuildKernel).
    """

    import subprocess
    import sys

    code = (
        "import sys; import mycad.core.groups; "
        'bad = {"build123d", "OCP", "numpy"} & set(sys.modules); '
        "print(','.join(sorted(bad)))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert not result.stdout.strip(), (
        f"groups leaked CAD/numpy modules: {result.stdout.strip()!r}; check imports"
    )
