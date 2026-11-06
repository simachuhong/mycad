# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Resolve replayed spatial definitions without exposing backend topology."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Literal, cast

from mycad.core.exceptions import TopologyReferenceError, ValidationError
from mycad.core.sketch import WorkPlaneFrame
from mycad.core.spatial_evaluation import evaluate_coordinate, evaluate_offset, evaluate_principal
from mycad.core.spatial_frames import RigidFrame
from mycad.core.spatial_references import SpatialReference, resolve_prior_output


def _prior_reference(
    value: object, outputs: Mapping[str, tuple[str, object]], command_id: str, path: str
) -> SpatialReference:
    try:
        reference = SpatialReference.from_mapping(value)
    except ValidationError as exc:
        raise TopologyReferenceError(
            exc.message, command_id=command_id, reason="invalid-reference", parameter_path=path
        ) from exc
    if reference.kind != "world":
        output = outputs.get(reference.source_instance_id or "")
        if output is None:
            raise TopologyReferenceError(
                "spatial source is missing or not yet created",
                command_id=command_id,
                reason="missing-reference",
                parameter_path=path,
            )
        if output[0] != reference.kind:
            raise TopologyReferenceError(
                "spatial source has the wrong type",
                command_id=command_id,
                reason="wrong-kind",
                parameter_path=path,
            )
    return reference


def evaluate_datum(
    command_id: str, params: Mapping[str, object], outputs: Mapping[str, tuple[str, object]]
) -> tuple[str, object]:
    """Evaluate one identity-scoped definition from earlier replay outputs."""
    try:
        if command_id == "datum.coordinate_system.create":
            frame = WorkPlaneFrame.from_mapping(
                {
                    "origin_mm": params["origin_mm"],
                    "u_axis": params["x_axis"],
                    "v_axis": params["y_axis"],
                    "normal": params["z_axis"],
                }
            )
            local = RigidFrame(frame.origin_mm, frame.u_axis, frame.v_axis, frame.normal)
            result = evaluate_coordinate(
                _prior_reference(params["parent"], outputs, command_id, "parent"), local, outputs
            )
            return "coordinate_system", result
        construction = cast("Mapping[str, object]", params["construction"])
        if construction["kind"] == "principal":
            plane = cast("Literal['xy', 'xz', 'yz']", construction["plane"])
            result_plane = evaluate_principal(
                _prior_reference(
                    construction["coordinate_system"],
                    outputs,
                    command_id,
                    "construction.coordinate_system",
                ),
                plane,
                outputs,
            )
        else:
            result_plane = evaluate_offset(
                _prior_reference(construction["plane"], outputs, command_id, "construction.plane"),
                cast("float", construction["distance_mm"]),
                outputs,
            )
        return "datum_plane", result_plane
    except (TypeError, ValueError, KeyError) as exc:
        raise ValidationError(str(exc), command_id=command_id) from exc


def associated_frame(
    support: Mapping[str, object], outputs: Mapping[str, tuple[str, object]]
) -> WorkPlaneFrame:
    """Build the sketch frame from its parent plane and explicit local placement."""
    try:
        reference = _prior_reference(support["plane"], outputs, "sketch.create", "support.plane")
        if reference.kind != "datum_plane":
            raise ValueError("sketch support must reference a datum plane")
        parent = resolve_prior_output(reference, outputs)
        if not isinstance(parent, WorkPlaneFrame):
            raise ValueError("datum plane has invalid frame")
        uv = cast("list[float]", support["offset_uv_mm"])
        origin = parent.local_to_world((uv[0], uv[1]))
        angle = math.radians(cast("float", support["rotation_deg"]))
        c, s = math.cos(angle), math.sin(angle)
        flip = cast("bool", support["flip_normal"])
        factor = -1.0 if flip else 1.0
        v_axis = tuple(factor * value for value in parent.v_axis)
        normal = tuple(factor * value for value in parent.normal)
        u = tuple(c * a + s * b for a, b in zip(parent.u_axis, v_axis, strict=True))
        v = tuple(-s * a + c * b for a, b in zip(parent.u_axis, v_axis, strict=True))
        return WorkPlaneFrame(
            origin,
            cast("tuple[float, float, float]", u),
            cast("tuple[float, float, float]", v),
            cast("tuple[float, float, float]", normal),
        )
    except (TypeError, ValueError, KeyError, IndexError) as exc:
        raise ValidationError(str(exc), command_id="sketch.create") from exc
