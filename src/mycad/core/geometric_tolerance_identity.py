# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Prepare identity repairs for annotations in legacy drawings."""

from dataclasses import replace
from uuid import uuid4

from mycad.core.detached_dimension import DetachedDimension
from mycad.core.geometric_tolerance import DatumIdentifier, FeatureControlFrame


def repair_annotation_identities(
    frames: tuple[FeatureControlFrame, ...],
    datums: tuple[DatumIdentifier, ...],
    references: tuple[DetachedDimension, ...],
) -> tuple[dict[str, object], dict[str, object]]:
    """Preserve datum identities and change only colliding frame/reference IDs."""
    datum_ids = {datum.datum_id for datum in datums}
    reference_ids = {reference.dimension_id for reference in references}
    reserved = {frame.frame_id for frame in frames} | datum_ids | reference_ids

    def new_id() -> str:
        identity = uuid4().hex
        while identity in reserved:
            identity = uuid4().hex
        reserved.add(identity)
        return identity

    changed_frames = [frame for frame in frames if frame.frame_id in datum_ids | reference_ids]
    changed_references = [ref for ref in references if ref.dimension_id in datum_ids]
    frame_params: dict[str, object] = {
        "remove_frames": [frame.frame_id for frame in changed_frames],
        "add_frames": [replace(frame, frame_id=new_id()).to_mapping() for frame in changed_frames],
    }
    reference_params: dict[str, object] = {
        "remove": [ref.dimension_id for ref in changed_references],
        "add": [replace(ref, dimension_id=new_id()).to_mapping() for ref in changed_references],
    }
    return frame_params, reference_params
