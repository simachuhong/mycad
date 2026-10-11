# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Plan-file loader (T10b): the single Appendix B.1 validator.

``run --json`` and ``validate <file.json>`` share :func:`load_plan_file`, so a
plan that validates is exactly a plan that runs. Every violation raises a
one-line ``ValidationError`` / ``UnknownCommandError`` (exit code 1).
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from mycad.commands.validation import validate_params
from mycad.core.document import AFFECTED_OBJECTS, METADATA_KEYS, AffectedObject, PlannedCommand
from mycad.core.exceptions import ValidationError

if TYPE_CHECKING:
    from mycad.commands.registry import CommandRegistry

__all__ = ["Outputs", "ValidatedPlan", "load_plan_file", "validate_plan_dict"]

_TOP_KEYS = ("plan_id", "metadata", "steps", "outputs")
_REQUIRED_METADATA = ("part_no", "revision", "material", "source")
_STEP_KEYS = ("id", "version", "params", "affected_object")
_OUTPUT_KEYS = ("step", "stl", "archive")
_PLAN_ID = re.compile(r"^[0-9a-f]{32}$")


@dataclass(frozen=True)
class Outputs:
    """Declared export targets, resolved against the plan file's directory."""

    step: Path | None = None
    stl: Path | None = None
    archive: Path | None = None


@dataclass(frozen=True)
class ValidatedPlan:
    plan_id: str
    plan_metadata: dict[str, str]
    steps: tuple[PlannedCommand, ...]
    outputs: Outputs


def _object(value: object, where: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValidationError(f"{where}: expected object")
    return cast("dict[str, object]", value)


def _reject_unknown(data: dict[str, object], allowed: tuple[str, ...], where: str) -> None:
    unknown = sorted(set(data) - set(allowed))
    if unknown:
        raise ValidationError(f"{where}: unknown key(s) {unknown}")


def _metadata(value: object) -> dict[str, str]:
    data = _object(value, "metadata")
    _reject_unknown(data, METADATA_KEYS, "metadata")
    missing = [key for key in _REQUIRED_METADATA if key not in data]
    if missing:
        raise ValidationError(f"metadata: missing required key(s) {missing}")
    for key, item in data.items():
        if not isinstance(item, str):
            raise ValidationError(f"metadata.{key}: expected string")
    return cast("dict[str, str]", dict(data))


def _step(value: object, index: int, registry: CommandRegistry) -> PlannedCommand:
    where = f"steps[{index}]"
    data = _object(value, where)
    _reject_unknown(data, _STEP_KEYS, where)
    missing = [key for key in _STEP_KEYS if key not in data]
    if missing:
        raise ValidationError(f"{where}: missing required key(s) {missing}")
    command_id = data["id"]
    if not isinstance(command_id, str):
        raise ValidationError(f"{where}.id: expected string")
    spec = registry.get(command_id)
    version = data["version"]
    if isinstance(version, bool) or version != spec.version:
        raise ValidationError(f"{where}.version: expected {spec.version}, got {version!r}")
    params = _object(data["params"], f"{where}.params")
    try:
        validated = validate_params(spec, params, defs=registry.schema_defs)
    except ValidationError as exc:
        raise ValidationError(f"{where}.params: {exc}") from exc
    expected = AFFECTED_OBJECTS.get(command_id)
    if data["affected_object"] != expected:
        raise ValidationError(
            f"{where}.affected_object: expected {expected!r}, got {data['affected_object']!r}"
        )
    return PlannedCommand(
        id=command_id,
        version=spec.version,
        params=validated,
        summary_en=spec.summary_en,
        affected_object=cast("AffectedObject", expected),
    )


def _outputs(value: object, base_dir: Path) -> Outputs:
    data = _object(value, "outputs")
    _reject_unknown(data, _OUTPUT_KEYS, "outputs")
    paths: dict[str, Path] = {}
    for key, item in data.items():
        if not isinstance(item, str) or not item:
            raise ValidationError(f"outputs.{key}: expected non-empty string")
        paths[key] = base_dir / item
    archive = paths.get("archive")
    if archive is not None and not archive.name.endswith(".mc.json"):
        raise ValidationError("outputs.archive: must end with .mc.json")
    return Outputs(step=paths.get("step"), stl=paths.get("stl"), archive=archive)


def validate_plan_dict(data: object, registry: CommandRegistry, *, base_dir: Path) -> ValidatedPlan:
    """Validate a parsed plan against Appendix B.1 + command schemas + B.2."""
    plan = _object(data, "plan")
    _reject_unknown(plan, _TOP_KEYS, "plan")
    for key in ("metadata", "steps"):
        if key not in plan:
            raise ValidationError(f"plan: missing required key {key!r}")
    plan_id = plan.get("plan_id", uuid.uuid4().hex)
    if not isinstance(plan_id, str) or not _PLAN_ID.match(plan_id):
        raise ValidationError(f"plan_id: expected 32 lowercase hex chars, got {plan_id!r}")
    metadata = _metadata(plan["metadata"])
    raw_steps = plan["steps"]
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValidationError("steps: expected a non-empty array")
    steps = tuple(
        _step(item, index, registry) for index, item in enumerate(cast("list[object]", raw_steps))
    )
    outputs = _outputs(plan["outputs"], base_dir) if "outputs" in plan else Outputs()
    return ValidatedPlan(plan_id, metadata, steps, outputs)


def load_plan_file(path: Path, registry: CommandRegistry) -> ValidatedPlan:
    """Read, parse and validate a plan file (relative outputs resolve beside it)."""
    try:
        data: object = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValidationError(f"invalid JSON: {exc}") from exc
    return validate_plan_dict(data, registry, base_dir=path.parent)
