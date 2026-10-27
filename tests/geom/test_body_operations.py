# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Geometry and replay contracts for selected-body operations."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

import pytest

from mycad.app import AppServices, build_app, new_document, open_app_document
from mycad.core.exceptions import GeometryBuildError, ValidationError
from mycad.core.persistence import LoadedDocument, save_document


def _box(
    loaded: LoadedDocument,
    *,
    center: tuple[float, float, float],
    size: float = 10.0,
    mode: str = "new",
) -> None:
    loaded.bus.execute(
        "feature.box",
        {
            "size_x": size,
            "size_y": size,
            "size_z": size,
            "center": list(center),
            "mode": mode,
        },
        "test",
    )


def _body_selector(services: AppServices, index: int) -> dict[str, object]:
    return services.kernel.interactive_body_selector(services.kernel.body_ids[index])


def _selector_center(selector: Mapping[str, object]) -> tuple[float, float, float]:
    center: object = selector["center_mm"]
    assert isinstance(center, (tuple, list))
    coordinates = cast("Sequence[object]", center)
    assert len(coordinates) == 3
    x, y, z = coordinates
    assert all(
        not isinstance(value, bool) and isinstance(value, int | float) for value in coordinates
    )
    return (
        float(cast("int | float", x)),
        float(cast("int | float", y)),
        float(cast("int | float", z)),
    )


def _body_selector_near(
    services: AppServices, expected_center: tuple[float, float, float]
) -> dict[str, object]:
    matches: list[dict[str, object]] = []
    for identity in services.kernel.body_ids:
        selector = services.kernel.interactive_body_selector(identity)
        if _selector_center(selector) == pytest.approx(expected_center, abs=1e-6):
            matches.append(selector)
    assert len(matches) == 1
    return matches[0]


def _centers(services: AppServices) -> tuple[tuple[float, float, float], ...]:
    centers: list[tuple[float, float, float]] = []
    for identity in services.kernel.body_ids:
        selector = services.kernel.interactive_body_selector(identity)
        centers.append(_selector_center(selector))
    return tuple(sorted(centers))


def _assert_centers(
    actual: tuple[tuple[float, float, float], ...],
    expected: tuple[tuple[float, float, float], ...],
) -> None:
    assert len(actual) == len(expected)
    for actual_center, expected_center in zip(actual, expected, strict=True):
        assert actual_center == pytest.approx(expected_center, abs=1e-6)


def _overlapping_pair() -> tuple[AppServices, LoadedDocument]:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    _box(loaded, center=(0.0, 0.0, 0.0))
    loaded.bus.execute(
        "modify.body_transform",
        {
            "body": _body_selector(services, 0),
            "transform": {"operation": "copy", "translation_mm": [5.0, 0.0, 0.0]},
        },
        "test",
    )
    assert len(services.kernel.body_ids) == 2
    return services, loaded


@pytest.mark.parametrize(
    ("operation", "expected_volume"),
    (("union", 1500.0), ("difference", 500.0), ("intersection", 500.0)),
)
def test_selected_body_boolean_replaces_target_and_consumes_tool(
    operation: str, expected_volume: float
) -> None:
    services, loaded = _overlapping_pair()
    target, tool = _body_selector(services, 0), _body_selector(services, 1)

    loaded.bus.execute(
        "modify.boolean_bodies",
        {"operation": operation, "target_body": target, "tool_body": tool},
        "test",
    )

    props = services.kernel.mass_properties()
    assert props.volume == pytest.approx(expected_volume, abs=1e-6)
    assert props.solid_count == 1
    assert len(loaded.document.commands) == 3
    loaded.bus.undo()
    assert services.kernel.mass_properties().volume == pytest.approx(2000.0, abs=1e-6)
    assert services.kernel.mass_properties().solid_count == 2
    loaded.bus.redo()
    assert services.kernel.mass_properties().volume == pytest.approx(expected_volume, abs=1e-6)


def test_selected_body_union_can_keep_the_original_tool_body() -> None:
    services, loaded = _overlapping_pair()

    loaded.bus.execute(
        "modify.boolean_bodies",
        {
            "operation": "union",
            "target_body": _body_selector(services, 0),
            "tool_body": _body_selector(services, 1),
            "keep_tool": True,
        },
        "test",
    )

    props = services.kernel.mass_properties()
    assert props.volume == pytest.approx(2500.0, abs=1e-6)
    assert props.solid_count == 2


def test_empty_selected_body_intersection_does_not_write_history() -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    _box(loaded, center=(0.0, 0.0, 0.0))
    _box(loaded, center=(30.0, 0.0, 0.0), mode="add")
    before_commands = loaded.document.commands
    before_volume = services.kernel.mass_properties().volume

    with pytest.raises(GeometryBuildError, match="empty result"):
        loaded.bus.execute(
            "modify.boolean_bodies",
            {
                "operation": "intersection",
                "target_body": _body_selector(services, 0),
                "tool_body": _body_selector(services, 1),
            },
            "test",
        )

    assert loaded.document.commands == before_commands
    assert services.kernel.mass_properties().volume == pytest.approx(before_volume)
    assert services.kernel.mass_properties().solid_count == 2


def test_body_boolean_preserves_unrelated_body_and_replays_after_reopen(tmp_path: Path) -> None:
    services, loaded = _overlapping_pair()
    loaded.bus.execute(
        "modify.body_transform",
        {
            "body": _body_selector_near(services, (0.0, 0.0, 0.0)),
            "transform": {"operation": "copy", "translation_mm": [-50.0, 0.0, 0.0]},
        },
        "test",
    )

    loaded.bus.execute(
        "modify.boolean_bodies",
        {
            "operation": "intersection",
            "target_body": _body_selector_near(services, (0.0, 0.0, 0.0)),
            "tool_body": _body_selector_near(services, (5.0, 0.0, 0.0)),
        },
        "test",
    )

    assert services.kernel.mass_properties().volume == pytest.approx(1500.0, abs=1e-6)
    assert services.kernel.mass_properties().solid_count == 2
    _assert_centers(_centers(services), ((-50.0, 0.0, 0.0), (2.5, 0.0, 0.0)))
    archive_path = tmp_path / "body-boolean.mc.json"
    save_document(loaded.document, archive_path)

    reopened = open_app_document(services, archive_path)

    assert services.kernel.mass_properties().volume == pytest.approx(1500.0, abs=1e-6)
    assert services.kernel.mass_properties().solid_count == 2
    reopened.bus.undo()
    assert services.kernel.mass_properties().volume == pytest.approx(3000.0, abs=1e-6)
    assert services.kernel.mass_properties().solid_count == 3


@pytest.mark.parametrize(
    ("transform", "expected_centers"),
    (
        (
            {"operation": "move", "translation_mm": [0.0, 20.0, 0.0]},
            ((10.0, 20.0, 0.0),),
        ),
        (
            {
                "operation": "rotate",
                "axis_unit": [0.0, 0.0, 1.0],
                "center_mm": [0.0, 0.0, 0.0],
                "angle_deg": 90.0,
            },
            ((0.0, 10.0, 0.0),),
        ),
        (
            {
                "operation": "mirror",
                "plane_normal_unit": [1.0, 0.0, 0.0],
                "plane_origin_mm": [0.0, 0.0, 0.0],
            },
            ((-10.0, 0.0, 0.0),),
        ),
        (
            {"operation": "copy", "translation_mm": [0.0, 20.0, 0.0]},
            ((10.0, 0.0, 0.0), (10.0, 20.0, 0.0)),
        ),
    ),
)
def test_body_transform_is_replayable_and_changes_only_selected_body(
    transform: Mapping[str, object],
    expected_centers: tuple[tuple[float, float, float], ...],
) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    _box(loaded, center=(10.0, 0.0, 0.0))

    loaded.bus.execute(
        "modify.body_transform",
        {"body": _body_selector(services, 0), "transform": dict(transform)},
        "test",
    )

    _assert_centers(_centers(services), expected_centers)
    loaded.bus.undo()
    _assert_centers(_centers(services), ((10.0, 0.0, 0.0),))
    loaded.bus.redo()
    _assert_centers(_centers(services), expected_centers)


@pytest.mark.parametrize(
    ("pattern", "expected_centers"),
    (
        (
            {"kind": "linear", "count": 3, "spacing_mm": [20.0, 0.0, 0.0]},
            ((0.0, 0.0, 0.0), (20.0, 0.0, 0.0), (40.0, 0.0, 0.0)),
        ),
        (
            {
                "kind": "circular",
                "count": 4,
                "axis_unit": [0.0, 0.0, 1.0],
                "center_mm": [0.0, 0.0, 0.0],
                "angle_deg": 360.0,
            },
            ((-10.0, 0.0, 0.0), (0.0, -10.0, 0.0), (0.0, 10.0, 0.0), (10.0, 0.0, 0.0)),
        ),
        (
            {
                "kind": "circular",
                "count": 4,
                "axis_unit": [0.0, 0.0, 1.0],
                "center_mm": [0.0, 0.0, 0.0],
                "angle_deg": 180.0,
            },
            (
                (-10.0, 0.0, 0.0),
                (-5.0, 8.6602540378, 0.0),
                (5.0, 8.6602540378, 0.0),
                (10.0, 0.0, 0.0),
            ),
        ),
    ),
)
def test_body_patterns_keep_seed_and_include_expected_instances(
    pattern: Mapping[str, object],
    expected_centers: tuple[tuple[float, float, float], ...],
) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    seed_center = (0.0, 0.0, 0.0) if pattern["kind"] == "linear" else (10.0, 0.0, 0.0)
    _box(loaded, center=seed_center)

    loaded.bus.execute(
        "modify.body_pattern",
        {"seed_body": _body_selector(services, 0), "pattern": dict(pattern)},
        "test",
    )

    centers = _centers(services)
    assert len(centers) == len(expected_centers)
    _assert_centers(centers, expected_centers)
    assert services.kernel.mass_properties().volume == pytest.approx(
        1000.0 * len(expected_centers), abs=1e-6
    )


def test_body_pattern_rejects_a_nonfinite_translation() -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    _box(loaded, center=(0.0, 0.0, 0.0))
    before = loaded.document.commands

    with pytest.raises(ValidationError, match="finite numbers"):
        loaded.bus.execute(
            "modify.body_pattern",
            {
                "seed_body": _body_selector(services, 0),
                "pattern": {"kind": "linear", "count": 2, "spacing_mm": [math.inf, 0, 0]},
            },
            "test",
        )

    assert loaded.document.commands == before
