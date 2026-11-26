# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Isolated Qt font layout worker for command-line legacy DXF export."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from PySide6.QtWidgets import QApplication

from mycad.core.drawing_text import DrawingText, TextStyle, TextStyleTable
from mycad.core.geometric_tolerance import DatumIdentifier, FeatureControlFrame
from mycad.ui.font_manager import FontManager
from mycad.ui.geometric_tolerance_layout import (
    datum_box_size,
    frame_font_warning,
    layout_frame,
    legacy_frame_leader_layout,
)
from mycad.ui.text_layout import layout_text


def main() -> int:
    try:
        raw: object = json.load(sys.stdin)
        if not isinstance(raw, Mapping):
            raise ValueError("字体布局请求格式无效。")
        request = cast("Mapping[str, object]", raw)
        raw_frames = request.get("frames")
        if not isinstance(raw_frames, list):
            raise ValueError("公差框列表格式无效。")
        frames = tuple(
            FeatureControlFrame.from_mapping(item) for item in cast("Sequence[object]", raw_frames)
        )
        raw_datums = request.get("datums", [])
        if not isinstance(raw_datums, list):
            raise ValueError("基准列表格式无效。")
        datums = tuple(
            DatumIdentifier.from_mapping(item) for item in cast("Sequence[object]", raw_datums)
        )
        if any(datum.layout_mode != "legacy" for datum in datums) or len(
            {datum.datum_id for datum in datums}
        ) != len(datums):
            raise ValueError("旧基准身份或布局无效。")
        styles = TextStyleTable.from_mapping(request.get("styles"))
        app_name = request.get("application_name")
        if not isinstance(app_name, str) or not app_name:
            raise ValueError("应用名称无效。")
        application = QApplication([app_name])
        application.setApplicationName(app_name)
        directory = request.get("font_resource_directory")
        if directory is not None and (not isinstance(directory, str) or not directory):
            raise ValueError("字体资源目录无效。")
        manager = FontManager(Path(directory) if isinstance(directory, str) else None)
        anchors: dict[str, tuple[float, float]] = {}
        skipped: dict[str, int] = {}
        bounds: dict[str, tuple[float, float, float, float]] = {}
        notices: list[str] = []
        datum_boxes: dict[str, tuple[float, float]] = {}
        for frame in frames:
            if frame.leader_target_mm is None or frame.leader_anchor_offset is not None:
                raise ValueError("公差框不需要旧锚点计算。")
            try:
                style = styles.get(frame.text_style_id) if frame.text_style_id else TextStyle()
            except KeyError:
                style = None
            layout = layout_frame(frame, manager, style)
            rect = layout.bounds
            result = legacy_frame_leader_layout(frame, manager, style, bounds=rect)
            if result is None:
                raise ValueError(f"公差框 {frame.frame_id[:8]} 的引线无法计算框侧锚点。")
            anchor, count = result
            anchors[frame.frame_id] = (
                anchor[0] - frame.position_mm[0],
                anchor[1] - frame.position_mm[1],
            )
            if count:
                skipped[frame.frame_id] = count
            bounds[frame.frame_id] = (rect.left(), rect.top(), rect.right(), rect.bottom())
            warning = frame_font_warning(frame, manager, style, layout=layout)
            if warning:
                notices.append(f"公差框 {frame.frame_id[:8]} 的导出锚点：{warning}")
        for datum in datums:
            try:
                style = styles.get(datum.text_style_id) if datum.text_style_id else TextStyle()
            except KeyError:
                style = None
            actual_style = style or TextStyle()
            text = DrawingText("0" * 32, datum.label, (0, 0))
            label = layout_text(text, actual_style, manager)
            datum_boxes[datum.datum_id] = datum_box_size(datum, label, actual_style)
            replacement = manager.substitution(actual_style)
            warning = (
                f"文字样式 {datum.text_style_id} 不可用，使用默认样式显示。"
                if style is None
                else f"字体 {style.font_family or style.font_file} 不可用，使用 {replacement} 显示。"
                if replacement
                else ""
            )
            if label.missing_glyphs:
                warning += f"缺少字符：{label.missing_glyphs}。"
            if warning:
                notices.append(f"基准 {datum.datum_id[:8]} 的导出框：{warning}")
        print(
            json.dumps(
                {
                    "anchors": anchors,
                    "skipped": skipped,
                    "bounds": bounds,
                    "datum_boxes": datum_boxes,
                    "notices": notices,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (KeyError, TypeError, ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
