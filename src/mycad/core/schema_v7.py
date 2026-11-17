# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""V7 records the immutable initial defaults of a drawing document."""

from __future__ import annotations

import math
from typing import cast

from mycad.core.exceptions import ValidationError
from mycad.core.schema_v6 import validate_archive_v6

ARCHIVE_VERSION_V7 = 7


def validate_archive_v7(data: object, *, max_reference_version: int = 7) -> None:
    if not isinstance(data, dict):
        raise ValidationError("archive: expected object")
    root = cast("dict[str, object]", data)
    if type(root.get("version")) is not int or root["version"] != ARCHIVE_VERSION_V7:
        raise ValidationError("archive/version: expected integer 7")
    defaults = root.get("drawing_defaults")
    if root.get("document_type") == "drawing2d":
        if not isinstance(defaults, dict):
            raise ValidationError("archive/drawing_defaults: expected fillet_radius")
        fields = cast("dict[str, object]", defaults)
        if set(fields) != {"fillet_radius"}:
            raise ValidationError("archive/drawing_defaults: expected fillet_radius")
        radius = fields["fillet_radius"]
        try:
            valid = (
                not isinstance(radius, bool)
                and isinstance(radius, int | float)
                and math.isfinite(radius)
                and radius >= 0
            )
        except OverflowError:
            valid = False
        if not valid:
            raise ValidationError(
                "archive/drawing_defaults/fillet_radius: expected nonnegative finite number"
            )
    elif "drawing_defaults" in root:
        raise ValidationError("archive/drawing_defaults: only drawing documents have defaults")
    legacy = {key: value for key, value in root.items() if key != "drawing_defaults"}
    legacy["version"] = 6
    validate_archive_v6(legacy, max_reference_version=max_reference_version)
