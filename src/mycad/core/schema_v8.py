# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""V8 records the initial chamfer angle alongside the fillet radius."""

from __future__ import annotations

import math
from typing import cast

from mycad.core.exceptions import ValidationError
from mycad.core.schema_v7 import validate_archive_v7

ARCHIVE_VERSION_V8 = 8


def validate_archive_v8(data: object) -> None:
    if not isinstance(data, dict):
        raise ValidationError("archive: expected object")
    root = cast("dict[str, object]", data)
    if type(root.get("version")) is not int or root["version"] != ARCHIVE_VERSION_V8:
        raise ValidationError("archive/version: expected integer 8")
    legacy = dict(root)
    legacy["version"] = 7
    if root.get("document_type") == "drawing2d":
        defaults = root.get("drawing_defaults")
        if not isinstance(defaults, dict):
            raise ValidationError(
                "archive/drawing_defaults: expected fillet_radius and chamfer_angle"
            )
        fields = cast("dict[str, object]", defaults)
        if set(fields) != {"fillet_radius", "chamfer_angle"}:
            raise ValidationError(
                "archive/drawing_defaults: expected fillet_radius and chamfer_angle"
            )
        angle = fields["chamfer_angle"]
        try:
            valid = (
                not isinstance(angle, bool)
                and isinstance(angle, int | float)
                and math.isfinite(angle)
                and 0 <= angle < 180
            )
        except OverflowError:
            valid = False
        if not valid:
            raise ValidationError(
                "archive/drawing_defaults/chamfer_angle: expected angle in [0, 180)"
            )
        legacy["drawing_defaults"] = {"fillet_radius": fields["fillet_radius"]}
    validate_archive_v7(legacy, max_reference_version=ARCHIVE_VERSION_V8)
