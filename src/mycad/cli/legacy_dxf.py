# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Request optional desktop font metrics without loading Qt into the CLI."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from mycad.core.drawing_text import TextStyleTable
from mycad.core.exceptions import ValidationError
from mycad.core.geometric_tolerance import DatumIdentifier, FeatureControlFrame
from mycad.formats.dxf_datum import DatumNativeSnapshot


class LegacyQtUnavailable(ValidationError):
    """Optional Qt dependency is absent; datum-only export can use its warned fallback."""


def legacy_layout_snapshot(
    frames: tuple[FeatureControlFrame, ...],
    styles: TextStyleTable,
    *,
    datums: tuple[DatumIdentifier, ...] = (),
    font_resource_directory: Path | None = None,
) -> tuple[
    dict[str, tuple[float, float]],
    dict[str, int],
    dict[str, tuple[float, float, float, float]],
    tuple[str, ...],
    dict[str, DatumNativeSnapshot],
]:
    """Ask an isolated optional Qt worker to use the same font layout as the canvas."""
    subject = "旧公差框和基准" if frames and datums else "旧公差框" if frames else "旧基准"
    request = {
        "frames": [frame.to_mapping() for frame in frames],
        "datums": [datum.to_mapping() for datum in datums],
        "styles": styles.to_mapping(),
        "application_name": Path(sys.argv[0]).name or "mycad",
        "font_resource_directory": str(font_resource_directory)
        if font_resource_directory
        else None,
    }
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONIOENCODING"] = "utf-8"
    command = (
        [str(Path(sys.executable).with_name("MyCAD-cli.exe")), "--legacy-layout"]
        if getattr(sys, "frozen", False)
        else [sys.executable, "-m", "mycad.ui.legacy_frame_export"]
    )
    try:
        result = subprocess.run(
            command,
            input=json.dumps(request, ensure_ascii=False),
            encoding="utf-8",
            capture_output=True,
            timeout=30,
            env=env,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except (OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
        raise ValidationError(f"{subject}字体布局进程不可用或超时，DXF 未导出。") from exc
    if result.returncode:
        if "No module named 'PySide6'" in result.stderr:
            raise LegacyQtUnavailable(f"{subject}需要桌面字体组件，但该组件未安装；DXF 未导出。")
        try:
            failure: object = json.loads(result.stdout)
            if isinstance(failure, Mapping):
                reason = cast("Mapping[str, object]", failure).get("error")
                if isinstance(reason, str) and reason.strip():
                    raise ValidationError(f"{subject}字体布局失败：{reason.splitlines()[0][:500]}")
        except json.JSONDecodeError:
            pass
        raise ValidationError(f"{subject}字体布局失败；请安装桌面依赖并检查字体或在画布中导出。")
    try:
        raw: object = json.loads(result.stdout)
        if not isinstance(raw, Mapping):
            raise ValueError("invalid snapshot")
        payload = cast("Mapping[str, object]", raw)
        raw_anchors, raw_skipped, raw_bounds, raw_notices = (
            payload.get("anchors"),
            payload.get("skipped"),
            payload.get("bounds"),
            payload.get("notices"),
        )
        raw_datum_boxes = payload.get("datum_boxes", {})
        if (
            not isinstance(raw_anchors, Mapping)
            or not isinstance(raw_skipped, Mapping)
            or not isinstance(raw_bounds, Mapping)
            or not isinstance(raw_datum_boxes, Mapping)
        ):
            raise ValueError("invalid mappings")
        if not isinstance(raw_notices, list):
            raise ValueError("invalid notices")
        notices = cast("list[object]", raw_notices)
        if any(not isinstance(item, str) for item in notices):
            raise ValueError("invalid notices")
        anchor_mapping = cast("Mapping[object, object]", raw_anchors)
        skipped_mapping = cast("Mapping[object, object]", raw_skipped)
        bounds_mapping = cast("Mapping[object, object]", raw_bounds)
        datum_mapping = cast("Mapping[object, object]", raw_datum_boxes)
        if set(anchor_mapping) != {frame.frame_id for frame in frames}:
            raise ValueError("frame identities differ")
        if set(bounds_mapping) != set(anchor_mapping):
            raise ValueError("frame bounds identities differ")
        expected_datums = {datum.datum_id: datum for datum in datums}
        if len(expected_datums) != len(datums) or set(datum_mapping) != set(expected_datums):
            raise ValueError("datum identities differ")
        anchors: dict[str, tuple[float, float]] = {}
        for key, point in anchor_mapping.items():
            if not isinstance(key, str) or not isinstance(point, list):
                raise ValueError("invalid anchor")
            values = cast("Sequence[object]", point)
            if len(values) != 2:
                raise ValueError("invalid anchor")
            if any(
                isinstance(value, bool) or not isinstance(value, int | float) for value in values
            ):
                raise ValueError("invalid coordinates")
            anchors[key] = (float(cast("float", values[0])), float(cast("float", values[1])))
        skipped: dict[str, int] = {}
        for key, value in skipped_mapping.items():
            if not isinstance(key, str) or isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("invalid skipped count")
            skipped[key] = value
        bounds: dict[str, tuple[float, float, float, float]] = {}
        for key, value in bounds_mapping.items():
            if not isinstance(key, str) or not isinstance(value, list):
                raise ValueError("invalid bounds")
            coordinates = cast("list[object]", value)
            if len(coordinates) != 4 or any(
                isinstance(item, bool) or not isinstance(item, int | float) for item in coordinates
            ):
                raise ValueError("invalid bounds")
            bounds[key] = (
                float(cast("float", coordinates[0])),
                float(cast("float", coordinates[1])),
                float(cast("float", coordinates[2])),
                float(cast("float", coordinates[3])),
            )
        datum_snapshots: dict[str, DatumNativeSnapshot] = {}
        for key, value in datum_mapping.items():
            if not isinstance(key, str) or not isinstance(value, list):
                raise ValueError("invalid datum box")
            dimensions = cast("list[object]", value)
            if len(dimensions) != 2 or any(
                isinstance(item, bool)
                or not isinstance(item, int | float)
                or not math.isfinite(item)
                or item <= 0
                for item in dimensions
            ):
                raise ValueError("invalid datum dimensions")
            datum_snapshots[key] = DatumNativeSnapshot(
                expected_datums[key],
                float(cast("float", dimensions[0])),
                float(cast("float", dimensions[1])),
            )
        return anchors, skipped, bounds, tuple(cast("list[str]", notices)), datum_snapshots
    except (TypeError, ValueError, OverflowError, json.JSONDecodeError) as exc:
        raise ValidationError(f"{subject}字体布局结果无效，DXF 未导出。") from exc


def legacy_frame_snapshot(
    frames: tuple[FeatureControlFrame, ...],
    styles: TextStyleTable,
    *,
    font_resource_directory: Path | None = None,
) -> tuple[
    dict[str, tuple[float, float]],
    dict[str, int],
    dict[str, tuple[float, float, float, float]],
    tuple[str, ...],
]:
    """Compatibility wrapper for callers requesting only legacy frame anchors."""
    anchors, skipped, bounds, notices, _ = legacy_layout_snapshot(
        frames, styles, font_resource_directory=font_resource_directory
    )
    return anchors, skipped, bounds, notices
