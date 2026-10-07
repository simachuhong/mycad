# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Flange QA happy path (T7c): all eight built-in ids in one document.

Sequence relies on mode "new" replacing the whole solid (verified
against ``_b123_ops._combine``): box → extrude → revolve → cylinder
(flange blank) → fillet → boolean_cut → undo(2) → hole → hole_pattern.
Eight distinct command ids pass through the bus; the undo removes the
two destructive edits; the final state is the golden flange whose
volume matches the T11 analytic formula.
"""

from __future__ import annotations

import math

import pytest

from mycad.app import AppServices, build_app, new_document
from mycad.core.persistence import LoadedDocument

VOLUME_TOL = 1e-6


@pytest.fixture(scope="module")
def services() -> AppServices:
    return build_app(discoverers=[])


@pytest.fixture
def doc(services: AppServices) -> LoadedDocument:
    return new_document(services)


def _hole_params(diameter: float) -> dict[str, object]:
    return {
        "target_face": {"surface": "plane", "axis": "+Z", "rank": 0},
        "position": {"kind": "center"},
        "diameter": diameter,
        "depth": {"kind": "through_all"},
    }


def test_flange_qa_happy_path(doc: LoadedDocument, services: AppServices) -> None:
    doc.bus.execute("feature.box", {"size_x": 10.0, "size_y": 10.0, "size_z": 10.0})
    doc.bus.execute(
        "feature.extrude",
        {"profile": {"type": "circle", "radius": 5.0}, "distance": 10.0},
    )
    doc.bus.execute(
        "feature.revolve",
        {
            "profile": {"type": "rect", "width": 2.0, "height": 5.0, "center": [0.0, 10.0]},
            "axis": "X",
        },
    )
    doc.bus.execute("feature.cylinder", {"radius": 40.0, "height": 8.0})
    doc.bus.execute(
        "modify.fillet",
        {"edges": [{"parent_faces": [{"surface": "plane", "axis": "+Z"}]}], "radius": 1.0},
    )
    doc.bus.execute(
        "modify.boolean_cut",
        {"tool": {"type": "box", "size_x": 10.0, "size_y": 10.0, "size_z": 30.0}},
    )
    doc.bus.undo(2)
    doc.bus.execute("feature.hole", _hole_params(20.0))
    doc.bus.execute(
        "feature.hole_pattern",
        {
            "base_hole": _hole_params(6.0),
            "pattern": {"kind": "polar", "radius": 25.0, "count": 4},
        },
    )

    mass = services.kernel.mass_properties()
    assert mass.solid_count == 1
    assert mass.volume == pytest.approx(
        math.pi * 8.0 * (40.0**2 - 10.0**2 - 4 * 3.0**2), abs=VOLUME_TOL
    )

    ids = tuple(command.id for command in doc.document.commands)
    assert ids == (
        "feature.box",
        "feature.extrude",
        "feature.revolve",
        "feature.cylinder",
        "feature.hole",
        "feature.hole_pattern",
    )
