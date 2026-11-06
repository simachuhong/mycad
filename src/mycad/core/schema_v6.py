# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""V6 retains v5 identity and permits versioned spatial commands."""

from typing import cast

from mycad.core.exceptions import ValidationError
from mycad.core.schema_v5 import validate_archive_v5

ARCHIVE_VERSION_V6 = 6


def validate_archive_v6(data: object) -> None:
    if not isinstance(data, dict):
        raise ValidationError("archive: expected object")
    root = cast("dict[str, object]", data)
    if type(root.get("version")) is not int or root["version"] != 6:
        raise ValidationError("archive/version: expected integer 6")
    validate_archive_v5({**root, "version": 5}, max_reference_version=6)
