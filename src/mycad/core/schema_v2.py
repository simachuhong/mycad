# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Structural validation for v2 archives and their required provenance."""

from __future__ import annotations

from typing import cast

from mycad.core.exceptions import ValidationError
from mycad.core.schema_v1 import validate_archive

ARCHIVE_VERSION_V2 = 2
_TOP_LEVEL_KEYS = ("format", "version", "metadata", "commands", "named_groups", "provenance")
_PROVENANCE_KEYS = (
    "mycad",
    "python",
    "dependencies",
    "units",
    "geometry_policy_version",
    "plugins",
)
_PLUGIN_KEYS = (
    "command_id",
    "command_version",
    "distribution",
    "plugin_id",
    "plugin_version",
    "api_version",
)


def _object(value: object, pointer: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValidationError(f"{pointer}: expected object")
    return cast("dict[str, object]", value)


def _closed(data: dict[str, object], keys: tuple[str, ...], pointer: str) -> None:
    for key in keys:
        if key not in data:
            raise ValidationError(f"{pointer}: missing required field {key!r}")
    for key in data:
        if key not in keys:
            raise ValidationError(f"{pointer}/{key}: unknown key (allowed: {list(keys)})")


def _string_fields(data: dict[str, object], keys: tuple[str, ...], pointer: str) -> None:
    _closed(data, keys, pointer)
    for key in keys:
        value = data[key]
        if not isinstance(value, str) or not value:
            raise ValidationError(f"{pointer}/{key}: expected non-empty string")


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_provenance(value: object, commands: object) -> None:
    provenance = _object(value, "archive/provenance")
    _closed(provenance, _PROVENANCE_KEYS, "archive/provenance")

    mycad = _object(provenance["mycad"], "archive/provenance/mycad")
    _string_fields(mycad, ("version", "source_revision"), "archive/provenance/mycad")

    python = _object(provenance["python"], "archive/provenance/python")
    _string_fields(python, ("implementation", "version"), "archive/provenance/python")

    dependencies = _object(provenance["dependencies"], "archive/provenance/dependencies")
    dependency_keys = ("build123d", "ocp", "occt")
    dependency_keys_with_solver = (*dependency_keys, "planegcs")
    if set(dependencies) not in (set(dependency_keys), set(dependency_keys_with_solver)):
        raise ValidationError(
            "archive/provenance/dependencies: expected build123d, ocp, occt, and optional planegcs"
        )
    _string_fields(
        dependencies,
        dependency_keys if "planegcs" not in dependencies else dependency_keys_with_solver,
        "archive/provenance/dependencies",
    )

    units = _object(provenance["units"], "archive/provenance/units")
    _closed(units, ("length", "angle"), "archive/provenance/units")
    if units["length"] != "mm":
        raise ValidationError("archive/provenance/units/length: expected 'mm'")
    if units["angle"] != "deg":
        raise ValidationError("archive/provenance/units/angle: expected 'deg'")

    policy = provenance["geometry_policy_version"]
    if not isinstance(policy, str) or not policy:
        raise ValidationError(
            "archive/provenance/geometry_policy_version: expected non-empty string"
        )

    plugins_value = provenance["plugins"]
    if not isinstance(plugins_value, list):
        raise ValidationError("archive/provenance/plugins: expected array")
    command_keys: set[tuple[str, int]] = set()
    for index, item in enumerate(cast("list[object]", plugins_value)):
        pointer = f"archive/provenance/plugins/{index}"
        plugin = _object(item, pointer)
        _closed(plugin, _PLUGIN_KEYS, pointer)
        _string_fields(
            {key: plugin[key] for key in _PLUGIN_KEYS if key != "command_version"},
            tuple(key for key in _PLUGIN_KEYS if key != "command_version"),
            pointer,
        )
        command_id = plugin["command_id"]
        command_version = plugin["command_version"]
        if not _is_int(command_version) or cast("int", command_version) < 1:
            raise ValidationError(f"{pointer}/command_version: expected integer >= 1")
        identity = (cast("str", command_id), cast("int", command_version))
        if identity in command_keys:
            raise ValidationError(f"{pointer}: duplicate plugin command identity")
        command_keys.add(identity)

    history_keys: set[tuple[str, int]] = set()
    for raw_command in cast("list[object]", commands):
        entry = cast("dict[str, object]", raw_command)
        history_keys.add((cast("str", entry["id"]), cast("int", entry["version"])))
    missing = command_keys - history_keys
    if missing:
        command_id, command_version = sorted(missing)[0]
        raise ValidationError(
            "archive/provenance/plugins: identity references command absent from history "
            f"{command_id!r} version {command_version}"
        )


def validate_archive_v2(data: object) -> None:
    """Validate v2's closed top-level shape and provenance, then v1 payload rules."""
    root = _object(data, "archive")
    _closed(root, _TOP_LEVEL_KEYS, "archive")
    if root["format"] != "mycad.document":
        raise ValidationError("archive/format: expected 'mycad.document'")
    if not _is_int(root["version"]) or root["version"] != ARCHIVE_VERSION_V2:
        raise ValidationError("archive/version: expected integer 2")
    v1_payload = {key: value for key, value in root.items() if key != "provenance"}
    v1_payload["version"] = 1
    validate_archive(v1_payload)
    _validate_provenance(root["provenance"], root["commands"])


__all__ = ["ARCHIVE_VERSION_V2", "validate_archive_v2"]
