# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Operation inputs and results survive replay without guessing face ancestry."""

from __future__ import annotations

from pathlib import Path

import pytest

from mycad.app import build_app, new_document, open_app_document
from mycad.core.persistence import save_document


@pytest.mark.parametrize("keep_tool", [False, True])
def test_copy_and_boolean_publish_distinct_result_and_retained_tool_origins(
    tmp_path: Path, keep_tool: bool
) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 10.0, "size_y": 10.0, "size_z": 10.0}, "test")
    first = services.kernel.viewport_data()[-1].body_origins[0]
    assert first.result.state_id == "feature.box:0"
    assert first.result.solid_index == 0
    assert first.inputs == ()
    selector = services.kernel.interactive_body_selector(services.kernel.body_ids[0])
    loaded.bus.execute(
        "modify.body_transform",
        {"body": selector, "transform": {"operation": "copy", "translation_mm": [5.0, 0.0, 0.0]}},
        "test",
    )
    copied = services.kernel.viewport_data()[-1].body_origins
    assert copied[0].result == first.result
    assert copied[1].result.state_id == "modify.body_transform:1"
    assert copied[1].inputs[0].role == "source"
    assert copied[1].inputs[0].result == first.result
    target, tool = (
        services.kernel.interactive_body_selector(identity) for identity in services.kernel.body_ids
    )
    loaded.bus.execute(
        "modify.boolean_bodies",
        {
            "operation": "difference",
            "target_body": target,
            "tool_body": tool,
            "keep_tool": keep_tool,
        },
        "test",
    )
    result = services.kernel.viewport_data()[-1].body_origins
    assert len(result) == (2 if keep_tool else 1)
    assert result[0].result.state_id == "modify.boolean_bodies:2"
    assert tuple(item.role for item in result[0].inputs) == ("target", "tool")
    assert tuple(item.result for item in result[0].inputs) == (copied[0].result, copied[1].result)
    if keep_tool:
        assert result[1].result == copied[1].result
    signature = tuple((item.result, item.inputs) for item in result)
    loaded.bus.undo()
    assert tuple(item.result for item in services.kernel.viewport_data()[-1].body_origins) == tuple(
        item.result for item in copied
    )
    loaded.bus.redo()
    assert (
        tuple(
            (item.result, item.inputs) for item in services.kernel.viewport_data()[-1].body_origins
        )
        == signature
    )
    path = tmp_path / "body-origin.mc.json"
    save_document(loaded.document, path)
    open_app_document(services, path)
    reopened = services.kernel.viewport_data()[-1].body_origins
    assert tuple((item.result, item.inputs) for item in reopened) == signature
    assert tuple(item.body_id for item in reopened) == services.kernel.body_ids


@pytest.mark.parametrize("kind", ["linear", "circular"])
def test_pattern_results_keep_unrelated_body_and_seed_origins(kind: str) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    for center, mode in (([20, 0, 0], "new"), ([0, 0, 30], "add")):
        loaded.bus.execute(
            "feature.box",
            {"size_x": 2, "size_y": 2, "size_z": 2, "center": center, "mode": mode},
            "test",
        )
    before = services.kernel.viewport_data()[-1].body_origins
    pattern: dict[str, object] = {"kind": kind, "count": 3}
    if kind == "linear":
        pattern["spacing_mm"] = [10, 0, 0]
    else:
        pattern.update(axis_unit=[0, 0, 1], center_mm=[0, 0, 0], angle_deg=360)
    seed = services.kernel.interactive_body_selector(services.kernel.body_ids[0])
    loaded.bus.execute("modify.body_pattern", {"seed_body": seed, "pattern": pattern}, "test")
    after = services.kernel.viewport_data()[-1].body_origins
    assert len(after) == 4
    assert {origin.result for origin in before} <= {origin.result for origin in after}
    copies = [origin for origin in after if origin.result.state_id == "modify.body_pattern:2"]
    assert len(copies) == 2
    assert len({origin.result for origin in copies}) == 2
    assert all(len(origin.inputs) == 1 for origin in copies)
    assert all(origin.inputs[0].role == "seed" for origin in copies)
    assert all(origin.inputs[0].result == before[0].result for origin in copies)


def test_disjoint_boolean_target_is_new_result_and_failure_preserves_provenance() -> None:
    from mycad.core.exceptions import GeometryBuildError

    services = build_app(discoverers=[])
    loaded = new_document(services)
    for center, mode in (([0, 0, 0], "new"), ([20, 0, 0], "add"), ([40, 0, 0], "add")):
        loaded.bus.execute(
            "feature.box",
            {"size_x": 2, "size_y": 2, "size_z": 2, "center": center, "mode": mode},
            "test",
        )
    before = services.kernel.viewport_data()[-1].body_origins
    selectors = [
        services.kernel.interactive_body_selector(body) for body in services.kernel.body_ids
    ]
    # Tool before target exercises index shifting when the tool is consumed.
    params: dict[str, object] = {
        "operation": "intersection",
        "target_body": selectors[2],
        "tool_body": selectors[0],
        "keep_tool": False,
    }
    with pytest.raises(GeometryBuildError):
        loaded.bus.execute("modify.boolean_bodies", params, "test")
    unchanged = services.kernel.viewport_data()[-1].body_origins
    assert [(o.result, o.inputs) for o in unchanged] == [(o.result, o.inputs) for o in before]
    params["operation"] = "difference"
    loaded.bus.execute("modify.boolean_bodies", params, "test")
    after = services.kernel.viewport_data()[-1].body_origins
    assert len(after) == 2
    assert after[0].result == before[1].result
    assert after[1].result.state_id == "modify.boolean_bodies:3"
    assert after[1].result.solid_index == 1
    assert tuple(i.result for i in after[1].inputs) == (before[2].result, before[0].result)
