# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Explicit archive validation dispatch, including adopted source snapshots."""

from __future__ import annotations

from typing import cast

from mycad.core.exceptions import ValidationError


def validate_versioned_archive(data: object) -> None:
    from mycad.core.schema_v1 import validate_archive
    from mycad.core.schema_v2 import validate_archive_v2
    from mycad.core.schema_v3 import validate_archive_v3
    from mycad.core.schema_v4 import validate_archive_v4
    from mycad.core.schema_v5 import validate_archive_v5
    from mycad.core.schema_v6 import validate_archive_v6

    if not isinstance(data, dict):
        raise ValidationError("archive: expected object")
    root = cast("dict[str, object]", data)
    version = root.get("version")
    if type(version) is not int:
        raise ValidationError("archive/version: expected integer")
    validator = {
        1: validate_archive,
        2: validate_archive_v2,
        3: validate_archive_v3,
        4: validate_archive_v4,
        5: validate_archive_v5,
        6: validate_archive_v6,
    }.get(version)
    if validator is None:
        raise ValidationError("unsupported archive version")
    validator(root)
