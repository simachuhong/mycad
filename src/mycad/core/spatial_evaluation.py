# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Evaluate the first spatial constructions using already resolved outputs."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Literal

from mycad.core.exceptions import ValidationError
from mycad.core.sketch import WorkPlaneFrame
from mycad.core.spatial_frames import RigidFrame
from mycad.core.spatial_references import SpatialReference, resolve_prior_output

SpatialOutputs = Mapping[str, tuple[str, object]]


def _coordinate(reference: SpatialReference, outputs: SpatialOutputs) -> RigidFrame:
    if reference.kind == "world":
        return RigidFrame.identity()
    if reference.kind != "coordinate_system":
        raise ValidationError("expected coordinate system reference")
    result = resolve_prior_output(reference, outputs)
    if not isinstance(result, RigidFrame):
        raise ValidationError("coordinate output has invalid frame")
    return result


def evaluate_coordinate(
    parent: SpatialReference, local: RigidFrame, outputs: SpatialOutputs
) -> RigidFrame:
    """Compose a local definition with its previously evaluated parent."""
    return _coordinate(parent, outputs).compose(local)


def evaluate_principal(
    parent: SpatialReference, plane: Literal["xy", "xz", "yz"], outputs: SpatialOutputs
) -> WorkPlaneFrame:
    """Resolve a principal plane of a world or named coordinate system."""
    return _coordinate(parent, outputs).principal_plane(plane)


def evaluate_offset(
    parent: SpatialReference, distance_mm: float, outputs: SpatialOutputs
) -> WorkPlaneFrame:
    """Offset a previously evaluated plane along its oriented normal."""
    if parent.kind != "datum_plane":
        raise ValidationError("expected datum plane reference")
    if not math.isfinite(distance_mm):
        raise ValidationError("offset must be finite")
    frame = resolve_prior_output(parent, outputs)
    if not isinstance(frame, WorkPlaneFrame):
        raise ValidationError("datum output has invalid plane")
    origin = (
        frame.origin_mm[0] + distance_mm * frame.normal[0],
        frame.origin_mm[1] + distance_mm * frame.normal[1],
        frame.origin_mm[2] + distance_mm * frame.normal[2],
    )
    return WorkPlaneFrame(origin, frame.u_axis, frame.v_axis, frame.normal)
