# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Integration execution tests (T7c): all eight built-ins through the bus.

Every legal-execution case asserts analytic volume/solid_count on the
shared kernel after a bus execute; every validation case asserts the
framework's ValidationError; every grammar case round-trips a
default-filled param dict through to_cli + parse_line.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

import pytest

from mycad.app import AppServices, build_app, new_document
from mycad.commands.grammar import parse_line, to_cli
from mycad.commands.validation import validate_params
from mycad.core.exceptions import ValidationError
from mycad.core.persistence import LoadedDocument

VOLUME_TOL = 1e-6


@pytest.fixture(scope="module")
def services() -> AppServices:
    return build_app(discoverers=[])


@pytest.fixture
def doc(services: AppServices) -> LoadedDocument:
    return new_document(services)


def _roundtrip(services: AppServices, command_id: str, params: Mapping[str, object]) -> None:
    spec = services.registry.get(command_id)
    filled = validate_params(spec, params, defs=services.registry.schema_defs)
    text = to_cli(command_id, filled, services.registry)
    assert parse_line(text, services.registry) == (command_id, filled)


# --- feature.box --------------------------------------------------------------


def test_box_legal_execution(doc: LoadedDocument, services: AppServices) -> None:
    doc.bus.execute("feature.box", {"size_x": 10.0, "size_y": 20.0, "size_z": 30.0})
    mass = services.kernel.mass_properties()
    assert mass.solid_count == 1
    assert mass.volume == pytest.approx(6000.0, abs=VOLUME_TOL)


def test_box_zero_size_is_rejected(doc: LoadedDocument) -> None:
    with pytest.raises(ValidationError):
        doc.bus.execute("feature.box", {"size_x": 0.0, "size_y": 20.0, "size_z": 30.0})


def test_box_grammar_roundtrip(services: AppServices) -> None:
    _roundtrip(services, "feature.box", {"size_x": 10.0, "size_y": 20.0, "size_z": 30.0})


# --- feature.cylinder ---------------------------------------------------------


def test_cylinder_legal_execution(doc: LoadedDocument, services: AppServices) -> None:
    doc.bus.execute("feature.cylinder", {"radius": 40.0, "height": 8.0})
    mass = services.kernel.mass_properties()
    assert mass.solid_count == 1
    assert mass.volume == pytest.approx(math.pi * 1600.0 * 8.0, abs=VOLUME_TOL)


def test_cylinder_negative_radius_is_rejected(doc: LoadedDocument) -> None:
    with pytest.raises(ValidationError):
        doc.bus.execute("feature.cylinder", {"radius": -1.0, "height": 8.0})


def test_cylinder_grammar_roundtrip(services: AppServices) -> None:
    _roundtrip(services, "feature.cylinder", {"radius": 40.0, "height": 8.0})


# --- feature.extrude ----------------------------------------------------------


def test_extrude_legal_execution(doc: LoadedDocument, services: AppServices) -> None:
    doc.bus.execute(
        "feature.extrude",
        {"profile": {"type": "circle", "radius": 5.0}, "distance": 10.0},
    )
    mass = services.kernel.mass_properties()
    assert mass.solid_count == 1
    assert mass.volume == pytest.approx(math.pi * 25.0 * 10.0, abs=VOLUME_TOL)


def test_extrude_missing_distance_is_rejected(doc: LoadedDocument) -> None:
    with pytest.raises(ValidationError):
        doc.bus.execute("feature.extrude", {"profile": {"type": "circle", "radius": 5.0}})


def test_extrude_grammar_roundtrip(services: AppServices) -> None:
    _roundtrip(
        services,
        "feature.extrude",
        {"profile": {"type": "circle", "radius": 5.0}, "distance": 10.0},
    )


# --- feature.revolve ----------------------------------------------------------


def test_revolve_legal_execution(doc: LoadedDocument, services: AppServices) -> None:
    # The rect must sit entirely off the rotation axis (mirrors the
    # T2-era form): center [0, 10] keeps y in [7.5, 12.5], so sweeping
    # around X yields a washer of volume 2*pi*r_center*(w*h).
    doc.bus.execute(
        "feature.revolve",
        {
            "profile": {"type": "rect", "width": 2.0, "height": 5.0, "center": [0.0, 10.0]},
            "axis": "X",
        },
    )
    mass = services.kernel.mass_properties()
    assert mass.solid_count == 1
    assert mass.volume == pytest.approx(2 * math.pi * 10.0 * (2.0 * 5.0), abs=VOLUME_TOL)


def test_revolve_zero_angle_is_rejected(doc: LoadedDocument) -> None:
    with pytest.raises(ValidationError):
        doc.bus.execute(
            "feature.revolve",
            {
                "profile": {"type": "rect", "width": 2.0, "height": 5.0},
                "axis": "X",
                "angle_deg": 0.0,
            },
        )


def test_revolve_grammar_roundtrip(services: AppServices) -> None:
    _roundtrip(
        services,
        "feature.revolve",
        {
            "profile": {"type": "rect", "width": 2.0, "height": 5.0, "center": [0.0, 10.0]},
            "axis": "X",
        },
    )


# --- feature.hole -------------------------------------------------------------


def _hole_params(diameter: float) -> dict[str, object]:
    return {
        "target_face": {"surface": "plane", "axis": "+Z", "rank": 0},
        "position": {"kind": "center"},
        "diameter": diameter,
        "depth": {"kind": "through_all"},
    }


def test_hole_legal_execution(doc: LoadedDocument, services: AppServices) -> None:
    doc.bus.execute("feature.box", {"size_x": 30.0, "size_y": 30.0, "size_z": 10.0})
    doc.bus.execute("feature.hole", _hole_params(5.0))
    mass = services.kernel.mass_properties()
    assert mass.solid_count == 1
    assert mass.volume == pytest.approx(9000.0 - math.pi * 6.25 * 10.0, abs=VOLUME_TOL)


def test_hole_zero_diameter_is_rejected(doc: LoadedDocument) -> None:
    doc.bus.execute("feature.box", {"size_x": 30.0, "size_y": 30.0, "size_z": 10.0})
    with pytest.raises(ValidationError):
        doc.bus.execute("feature.hole", _hole_params(0.0))


def test_hole_grammar_roundtrip(services: AppServices) -> None:
    _roundtrip(services, "feature.hole", _hole_params(5.0))


# --- feature.hole_pattern -----------------------------------------------------


def _pattern_params() -> dict[str, object]:
    return {
        "base_hole": _hole_params(6.0),
        "pattern": {"kind": "polar", "radius": 25.0, "count": 4},
    }


def _flange_blank(doc: LoadedDocument) -> None:
    doc.bus.execute("feature.cylinder", {"radius": 40.0, "height": 8.0})
    doc.bus.execute("feature.hole", _hole_params(20.0))


def test_hole_pattern_legal_execution(doc: LoadedDocument, services: AppServices) -> None:
    _flange_blank(doc)
    doc.bus.execute("feature.hole_pattern", _pattern_params())
    mass = services.kernel.mass_properties()
    assert mass.solid_count == 1
    assert mass.volume == pytest.approx(math.pi * 8.0 * (1600.0 - 100.0 - 36.0), abs=VOLUME_TOL)


def test_hole_pattern_linear_kind_is_rejected(doc: LoadedDocument) -> None:
    _flange_blank(doc)
    params = _pattern_params()
    params["pattern"] = {"kind": "linear", "radius": 25.0, "count": 4}
    with pytest.raises(ValidationError):
        doc.bus.execute("feature.hole_pattern", params)


def test_hole_pattern_grammar_roundtrip(services: AppServices) -> None:
    _roundtrip(services, "feature.hole_pattern", _pattern_params())


# --- modify.fillet -------------------------------------------------------------


def _fillet_params() -> dict[str, object]:
    return {
        "edges": [{"parent_faces": [{"surface": "plane", "axis": "+Z"}]}],
        "radius": 1.0,
    }


def test_fillet_legal_execution(doc: LoadedDocument, services: AppServices) -> None:
    doc.bus.execute("feature.box", {"size_x": 10.0, "size_y": 10.0, "size_z": 10.0})
    before = services.kernel.mass_properties().volume
    doc.bus.execute("modify.fillet", _fillet_params())
    mass = services.kernel.mass_properties()
    assert mass.solid_count == 1
    assert mass.volume < 1000.0
    assert mass.volume < before


def test_fillet_zero_radius_is_rejected(doc: LoadedDocument) -> None:
    doc.bus.execute("feature.box", {"size_x": 10.0, "size_y": 10.0, "size_z": 10.0})
    params = _fillet_params()
    params["radius"] = 0.0
    with pytest.raises(ValidationError):
        doc.bus.execute("modify.fillet", params)


def test_fillet_residual_pattern_key_is_rejected(doc: LoadedDocument) -> None:
    doc.bus.execute("feature.box", {"size_x": 10.0, "size_y": 10.0, "size_z": 10.0})
    params = _fillet_params()
    params["pattern"] = {"kind": "linear"}
    with pytest.raises(ValidationError):
        doc.bus.execute("modify.fillet", params)


def test_fillet_grammar_roundtrip(services: AppServices) -> None:
    _roundtrip(services, "modify.fillet", _fillet_params())


# --- modify.boolean_cut -------------------------------------------------------


def _cut_params() -> dict[str, object]:
    return {"tool": {"type": "box", "size_x": 10.0, "size_y": 10.0, "size_z": 30.0}}


def test_boolean_cut_legal_execution(doc: LoadedDocument, services: AppServices) -> None:
    doc.bus.execute("feature.cylinder", {"radius": 40.0, "height": 8.0})
    doc.bus.execute("modify.boolean_cut", _cut_params())
    mass = services.kernel.mass_properties()
    assert mass.solid_count == 1
    assert mass.volume == pytest.approx(math.pi * 40.0**2 * 8.0 - 10.0 * 10.0 * 8.0, abs=VOLUME_TOL)


def test_boolean_cut_extra_mode_key_is_rejected(doc: LoadedDocument) -> None:
    doc.bus.execute("feature.cylinder", {"radius": 40.0, "height": 8.0})
    params = _cut_params()
    params["mode"] = "cut"
    with pytest.raises(ValidationError):
        doc.bus.execute("modify.boolean_cut", params)


def test_boolean_cut_grammar_roundtrip(services: AppServices) -> None:
    _roundtrip(services, "modify.boolean_cut", _cut_params())
