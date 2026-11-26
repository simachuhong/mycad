# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Rebind geometric annotation references when copying drawing selections."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import replace
from uuid import uuid4

from mycad.core.geometric_tolerance import (
    AnnotationAttachment,
    DatumIdentifier,
    DatumReference,
    FeatureControlFrame,
    ToleranceRow,
)
from mycad.core.geometric_tolerance_geometry import (
    relocate_automatic_leader,
    relocate_box_aware_leader,
)
from mycad.core.sketch import Point2D


def translate_frame(frame: FeatureControlFrame, delta: Point2D) -> FeatureControlFrame:
    dx, dy = delta
    target = frame.leader_target_mm
    return replace(
        frame,
        position_mm=(frame.position_mm[0] + dx, frame.position_mm[1] + dy),
        leader_target_mm=None if target is None else (target[0] + dx, target[1] + dy),
    )


def copy_geometric_annotations(
    frames: tuple[FeatureControlFrame, ...],
    datums: tuple[DatumIdentifier, ...],
    entity_mapping: Mapping[tuple[str, str], str],
    target_sketch_id: str,
    delta: Point2D,
    labels: Mapping[str, str],
    *,
    preserve_external: bool,
    reference_mapping: Mapping[str, str] | None = None,
    dimension_mapping: Mapping[tuple[str, str], str] | None = None,
    entity_sketch_mapping: Mapping[tuple[str, str], str] | None = None,
    dimension_sketch_mapping: Mapping[tuple[str, str], str] | None = None,
) -> tuple[tuple[FeatureControlFrame, ...], tuple[DatumIdentifier, ...]]:
    """Copy annotations, redirecting references within the copied selection.

    An external association is retained only when the caller has established
    that the destination is the same live document. In other documents it is
    detached without guessing from a label.
    """
    dx, dy = delta
    if not math.isfinite(dx) or not math.isfinite(dy):
        raise ValueError("copy translation must be finite")
    if len({datum.datum_id for datum in datums}) != len(datums):
        raise ValueError("duplicate source datum")
    if len({frame.frame_id for frame in frames}) != len(frames):
        raise ValueError("duplicate source frame")
    frame_mapping = {frame.frame_id: uuid4().hex for frame in frames}

    def destination(mapping: Mapping[tuple[str, str], str] | None, key: tuple[str, str]) -> str:
        if mapping is None:
            return target_sketch_id
        try:
            return mapping[key]
        except KeyError as exc:
            raise ValueError("复制关联缺少目标草图身份。") from exc

    def rebind(reference: AnnotationAttachment | None) -> tuple[AnnotationAttachment | None, bool]:
        if reference is None:
            return None, False
        mapped: str | None = None
        if reference.kind == "frame":
            mapped = frame_mapping.get(reference.object_id)
        elif reference.kind == "reference_dimension" and reference_mapping is not None:
            mapped = reference_mapping.get(reference.object_id)
        elif (
            reference.kind == "sketch_dimension"
            and dimension_mapping is not None
            and reference.sketch_id is not None
        ):
            mapped = dimension_mapping.get((reference.sketch_id, reference.object_id))
        if mapped is not None:
            return replace(
                reference,
                object_id=mapped,
                sketch_id=destination(
                    dimension_sketch_mapping, (reference.sketch_id, reference.object_id)
                )
                if reference.kind == "sketch_dimension" and reference.sketch_id is not None
                else None,
            ), False
        return (reference, True) if preserve_external else (None, False)

    copied_datums: list[DatumIdentifier] = []
    by_id: dict[str, DatumIdentifier] = {}
    for datum in datums:
        attachment = datum.attachment
        fixed_geometry_target = False
        annotation, target_stays = rebind(datum.annotation_attachment)
        target = (datum.target_mm[0] + dx, datum.target_mm[1] + dy)
        if target_stays:
            target = datum.target_mm
        if attachment is not None:
            mapped = entity_mapping.get((attachment.sketch_id, attachment.reference.entity_id))
            if mapped is not None:
                attachment = replace(
                    attachment,
                    sketch_id=destination(
                        entity_sketch_mapping,
                        (attachment.sketch_id, attachment.reference.entity_id),
                    ),
                    reference=replace(attachment.reference, entity_id=mapped),
                )
            elif preserve_external:
                target = datum.target_mm
                fixed_geometry_target = True
            else:
                attachment = None
        copied = replace(
            datum,
            datum_id=uuid4().hex,
            label=labels[datum.datum_id],
            position_mm=(datum.position_mm[0] + dx, datum.position_mm[1] + dy),
            target_mm=target,
            attachment=attachment,
            annotation_attachment=annotation,
            leader_auto_normal=datum.leader_auto_normal and attachment is not None,
            leader_auto_route=datum.leader_auto_route and attachment is not None,
            route_avoid_crossing=datum.route_avoid_crossing and attachment is not None,
            route_track_target=datum.route_track_target and attachment is not None,
            route_algorithm_version=datum.route_algorithm_version if attachment is not None else 1,
            spline_normal_enabled=datum.spline_normal_enabled and attachment is not None,
            surface_indication=(
                replace(
                    datum.surface_indication,
                    auto_normal=False,
                    auto_route=False,
                    route_avoid_crossing=False,
                )
                if attachment is None and datum.surface_indication is not None
                else datum.surface_indication
            ),
            leader_offsets=(
                relocate_box_aware_leader(
                    datum.position_mm,
                    datum.leader_offsets,
                    (datum.position_mm[0] + dx, datum.position_mm[1] + dy),
                    datum.target_mm,
                    datum.box_size_mm,
                    orthogonal_box_side=datum.route_algorithm_version >= 4,
                )
                if datum.route_algorithm_version >= 3
                and fixed_geometry_target
                and datum.box_size_mm is not None
                else relocate_automatic_leader(
                    datum.position_mm,
                    datum.leader_offsets,
                    (datum.position_mm[0] + dx, datum.position_mm[1] + dy),
                    datum.target_mm,
                )
                if datum.leader_auto_route and fixed_geometry_target
                else tuple((x - dx, y - dy) for x, y in datum.leader_offsets)
                if datum.leader_auto_normal and fixed_geometry_target
                else datum.leader_offsets
            ),
        )
        copied_datums.append(copied)
        by_id[datum.datum_id] = copied
    copied_frames: list[FeatureControlFrame] = []
    for frame in frames:
        attachment = frame.leader_attachment
        fixed_geometry_target = False
        annotation, target_stays = rebind(frame.leader_annotation_attachment)
        translated = translate_frame(frame, delta)
        if target_stays:
            translated = replace(translated, leader_target_mm=frame.leader_target_mm)
        if attachment is not None:
            mapped = entity_mapping.get((attachment.sketch_id, attachment.reference.entity_id))
            if mapped is not None:
                attachment = replace(
                    attachment,
                    sketch_id=destination(
                        entity_sketch_mapping,
                        (attachment.sketch_id, attachment.reference.entity_id),
                    ),
                    reference=replace(attachment.reference, entity_id=mapped),
                )
            elif preserve_external:
                translated = replace(translated, leader_target_mm=frame.leader_target_mm)
                fixed_geometry_target = True
            else:
                attachment = None
        rows: list[ToleranceRow] = []
        for row in frame.rows:
            refs: list[DatumReference] = []
            for ref in row.datums:
                copied_datum = by_id.get(ref.datum_id or "")
                if copied_datum is not None:
                    ref = replace(ref, datum_id=copied_datum.datum_id, label=copied_datum.label)
                elif not preserve_external:
                    ref = replace(ref, datum_id=None)
                refs.append(ref)
            rows.append(replace(row, datums=tuple(refs)))
        copied_frames.append(
            replace(
                translated,
                frame_id=frame_mapping[frame.frame_id],
                rows=tuple(rows),
                leader_attachment=attachment,
                leader_auto_normal=frame.leader_auto_normal and attachment is not None,
                leader_auto_route=frame.leader_auto_route and attachment is not None,
                route_avoid_crossing=frame.route_avoid_crossing and attachment is not None,
                route_track_target=frame.route_track_target and attachment is not None,
                route_algorithm_version=frame.route_algorithm_version
                if attachment is not None
                else 1,
                leader_offsets=(
                    relocate_automatic_leader(
                        frame.position_mm,
                        frame.leader_offsets,
                        translated.position_mm,
                        frame.leader_target_mm,
                        anchor=(
                            (
                                translated.position_mm[0] + frame.leader_anchor_offset[0],
                                translated.position_mm[1] + frame.leader_anchor_offset[1],
                            )
                            if frame.leader_anchor_offset is not None
                            else None
                        ),
                    )
                    if frame.leader_auto_route
                    and fixed_geometry_target
                    and frame.leader_target_mm is not None
                    else tuple((x - dx, y - dy) for x, y in frame.leader_offsets)
                    if frame.leader_auto_normal and fixed_geometry_target
                    else frame.leader_offsets
                ),
                leader_annotation_attachment=annotation,
                surface_indication=(
                    replace(
                        frame.surface_indication,
                        auto_normal=False,
                        auto_route=False,
                        route_avoid_crossing=False,
                    )
                    if attachment is None and frame.surface_indication is not None
                    else frame.surface_indication
                ),
            )
        )
    return tuple(copied_frames), tuple(copied_datums)
