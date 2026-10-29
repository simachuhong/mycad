# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Physical sheet decorations and output gate shared by every renderer."""

from dataclasses import dataclass

from mycad.core.drawing_projection import CurveGeometry, DrawingScene, LineCurve, Point2


@dataclass(frozen=True, slots=True)
class PaperText:
    position_mm: Point2
    text: str
    height_mm: float = 3.5
    layer: str = "DIM"
    rotation_deg: float = 0
    align: str = "left"


def validate_drawing_output(scene: DrawingScene) -> None:
    issues = list(scene.issues)
    if not any(view.curves for view in scene.views) and not scene.notes:
        issues.append("图纸缺少有效视图几何，请生成或更新视图")
    if len(scene.annotations) != len(scene.resolved_annotations):
        issues.append("标注尚未解析，请更新图纸")
    issues.extend(
        a.message or "标注失关联" for a in scene.resolved_annotations if a.status != "resolved"
    )
    if issues:
        raise ValueError("不能出图：" + "；".join(dict.fromkeys(issues)))


def _rectangle(x: float, y: float, width: float, height: float) -> tuple[LineCurve, ...]:
    points = ((x, y), (x + width, y), (x + width, y + height), (x, y + height))
    return tuple(LineCurve(a, b) for a, b in zip(points, (*points[1:], points[0]), strict=True))


def sheet_frame(scene: DrawingScene) -> tuple[CurveGeometry, ...]:
    if scene.template is not None:
        return scene.template.curves
    width, height = scene.size_mm
    margin = scene.margin_mm
    lines = _rectangle(margin, margin, width - 2 * margin, height - 2 * margin)
    if scene.title:
        lines += _rectangle(width - margin - 90, margin, 90, max(16, 5 * len(scene.title) + 5))
    return lines


def paper_texts(scene: DrawingScene) -> tuple[PaperText, ...]:
    width = scene.size_mm[0]
    margin = scene.margin_mm
    height = max(16, 5 * len(scene.title) + 5)
    title = tuple(
        PaperText(
            (width - margin - 88, margin + height - 2 - index * 5), f"{key}：{value}", 2.5, "FRAME"
        )
        for index, (key, value) in enumerate(scene.title)
    )
    if scene.template is not None:
        fields = {
            "比例": f"{scene.default_scale:g}:1"
            if scene.default_scale >= 1
            else f"1:{1 / scene.default_scale:g}",
            "页码": f"{scene.sheet_number}/{scene.sheet_count}",
            **dict(scene.title),
        }
        title = tuple(
            PaperText(
                t.position_mm,
                t.value(fields),
                _fit_height(t.value(fields), t.height_mm, t.width_mm),
                "FRAME",
                t.rotation_deg,
                t.align,
            )
            for t in scene.template.texts
            if t.value(fields)
        )
    labels = tuple(
        PaperText(a.position_mm, a.text, layer=a.layer)
        for a in scene.resolved_annotations
        if a.text
    )
    notes = tuple(
        PaperText(note.position_mm, note.text, note.height_mm, note.layer) for note in scene.notes
    )
    return (*title, *labels, *notes)


def _fit_height(value: str, height: float, width: float) -> float:
    # Conservative advance bound shared with DXF (which cannot depend on Qt fonts).
    if not width or not value:
        return height
    units = max(sum(1.5 if ord(c) > 255 else 1.1 for c in line) for line in value.split("\n"))
    return min(height, width / max(units, 1))
