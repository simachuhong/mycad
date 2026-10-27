# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Persistent sketch-layer contract tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

import pytest

from mycad.core.sketch_layers import (
    DEFAULT_SKETCH_LAYER,
    SketchLayer,
    SketchLayerTable,
)


def test_default_layer_is_present_and_uses_cad_drafting_defaults() -> None:
    table = SketchLayerTable()

    assert table.layers == (DEFAULT_SKETCH_LAYER,)
    assert table.get("0") == DEFAULT_SKETCH_LAYER
    assert DEFAULT_SKETCH_LAYER.linetype == "CONTINUOUS"
    assert DEFAULT_SKETCH_LAYER.visible
    assert not DEFAULT_SKETCH_LAYER.locked


def test_layer_properties_round_trip_through_json_mapping() -> None:
    layer = SketchLayer(
        name="DIMENSIONS",
        color_rgb=(21, 96, 130),
        linetype="DASHED",
        lineweight_mm=0.35,
        visible=False,
        locked=True,
    )

    assert SketchLayer.from_mapping(layer.to_mapping()) == layer


def test_layer_table_names_are_unique_case_insensitively() -> None:
    with pytest.raises(ValueError, match="already exists"):
        SketchLayerTable((DEFAULT_SKETCH_LAYER, SketchLayer("0")))


def test_layer_table_requires_layer_zero() -> None:
    with pytest.raises(ValueError, match="layer '0'"):
        SketchLayerTable((SketchLayer("OUTLINE"),))


@pytest.mark.parametrize(
    ("kwargs", "message"),
    (
        ({"name": ""}, "name"),
        ({"name": "bad/name"}, "name"),
        ({"color_rgb": (256, 0, 0)}, "color"),
        ({"color_rgb": (True, 0, 0)}, "color"),
        ({"linetype": "PHANTOM"}, "linetype"),
        ({"lineweight_mm": 0.27}, "lineweight"),
        ({"visible": 1}, "visibility"),
        ({"locked": 0}, "lock state"),
    ),
)
def test_layer_rejects_unsupported_or_invalid_properties(
    kwargs: dict[str, object], message: str
) -> None:
    values: dict[str, object] = {
        "name": "OUTLINE",
        "color_rgb": (40, 46, 52),
        "linetype": "CONTINUOUS",
        "lineweight_mm": 0.25,
        "visible": True,
        "locked": False,
    }
    values.update(kwargs)

    with pytest.raises(ValueError, match=message):
        cast("Callable[..., SketchLayer]", SketchLayer)(**values)
