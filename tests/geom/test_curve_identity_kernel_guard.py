# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Identity-bearing curves must not be silently downgraded by old edit paths."""

from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import cast
from uuid import uuid4

import pytest

from mycad.core.exceptions import ValidationError
from mycad.core.geometric_tolerance_topology import legacy_curve_point_identities
from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.geom.kernel import BuildKernel


@pytest.mark.parametrize("operation", ["revision", "constraint"])
def test_existing_edit_path_rejects_losing_curve_identities(operation: str) -> None:
    kernel = BuildKernel()
    entity_id = uuid4().hex
    ids = legacy_curve_point_identities(entity_id, "polyline", 3)
    entity = PolylineEntity(entity_id, ((0, 0), (10, 0), (10, 10)), point_ids=ids)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,))
    cast("dict[str, Sketch]", vars(kernel)["_sketches"])[sketch.sketch_id] = sketch
    stripped = replace(sketch, entities=(replace(entity, point_ids=()),)).to_state_mapping()
    params: dict[str, object] = {
        "sketch_id": sketch.sketch_id,
        "base_state_sha256": sketch.local_state_digest(),
    }
    if operation == "revision":
        params.update({"entities": stripped["entities"], "constraints": stripped["constraints"]})
    else:
        constraint = SketchConstraint(
            uuid4().hex, "horizontal", (SketchGeometryReference(entity_id, "segment", 0),)
        )
        params.update(
            {
                "constraint": constraint.to_mapping(),
                "solution_entities": stripped["entities"],
                "solver_id": "planegcs",
                "solver_version": "test",
                "degrees_of_freedom": 1,
            }
        )
        params["base_state_sha256"] = sketch.state_digest()
    with pytest.raises(ValidationError, match="身份"):
        if operation == "revision":
            revision = cast(
                "Callable[[BuildKernel, Mapping[str, object]], object]",
                vars(BuildKernel)["_prepare_sketch_revision"],
            )
            revision(kernel, params)
        else:
            constraint_update = cast(
                "Callable[[BuildKernel, Mapping[str, object], str], object]",
                vars(BuildKernel)["_apply_sketch_constraint"],
            )
            constraint_update(kernel, params, "sketch.constraint.add")
    assert kernel.sketches == (sketch,)


def test_array_spacing_rejects_result_that_loses_curve_identities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel = BuildKernel()
    entity_id = uuid4().hex
    ids = legacy_curve_point_identities(entity_id, "polyline", 3)
    entity = PolylineEntity(entity_id, ((0, 0), (10, 0), (10, 10)), point_ids=ids)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,))
    cast("dict[str, Sketch]", vars(kernel)["_sketches"])[sketch.sketch_id] = sketch
    changed = replace(sketch, entities=(replace(entity, point_ids=()),))

    def bad_result(*_args: object, **_kwargs: object) -> tuple[tuple[Sketch, ...], object]:
        return (changed,), object()

    monkeypatch.setattr("mycad.geom.kernel.update_array_spacing", bad_result)
    update = cast(
        "Callable[[BuildKernel, Mapping[str, object]], object]",
        vars(BuildKernel)["_update_associative_array"],
    )
    with pytest.raises(ValidationError, match="身份"):
        update(kernel, {"array_id": uuid4().hex, "row_spacing": 1, "column_spacing": 1})
    assert kernel.sketches == (sketch,)


def test_consumer_rebuild_rejects_curve_identity_loss_before_replay() -> None:
    kernel = BuildKernel()
    entity_id = uuid4().hex
    ids = legacy_curve_point_identities(entity_id, "polyline", 3)
    entity = PolylineEntity(entity_id, ((0, 0), (10, 0), (10, 10)), point_ids=ids)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,))
    cast("dict[str, Sketch]", vars(kernel)["_sketches"])[sketch.sketch_id] = sketch
    changed = replace(sketch, entities=(replace(entity, point_ids=()),))
    rebuild = cast(
        "Callable[[BuildKernel, Mapping[str, Sketch]], BuildKernel]",
        vars(BuildKernel)["_regenerate_with_sketches"],
    )
    with pytest.raises(ValidationError, match="身份"):
        rebuild(kernel, {sketch.sketch_id: changed})
    assert kernel.sketches == (sketch,)
