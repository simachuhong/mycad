# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""A measured 80 mm edge at 1:2 with exact conic and rational geometry."""

from uuid import uuid4

from mycad.core.drawing import DrawingAnnotation, DrawingSheet, DrawingState, DrawingView
from mycad.core.drawing_projection import (
    ArcCurve,
    DrawingScene,
    EllipseCurve,
    LineCurve,
    ProjectedCurve,
    ProjectionResult,
    SplineCurve,
    build_drawing_scene,
)
from mycad.core.drawing_references import DrawingGeometryReference, reference_for_curve


def drawing_scene() -> DrawingScene:
    sheet = DrawingSheet(
        uuid4(), title=(("名称", "法兰工程图"), ("图号", "MC-001"), ("比例", "1:2"))
    )
    view = DrawingView(uuid4(), sheet.sheet_id, anchor_mm=(60, 130), scale=0.5)
    line = ProjectedCurve(
        "line",
        LineCurve((0, 0), (80, 0)),
        source=DrawingGeometryReference("edge", (("fixture", 1),)),
    )
    curves = (
        line,
        ProjectedCurve("circle", ArcCurve((40, 30), 10)),
        ProjectedCurve("hidden", LineCurve((0, 5), (80, 5)), "hidden"),
        ProjectedCurve("ellipse", EllipseCurve((100, 30), 20, 10, 30)),
        ProjectedCurve(
            "spline",
            SplineCurve(((0, 40), (20, 70), (60, 10), (80, 40)), 3, (0, 1), (4, 4), (1, 2, 3, 1)),
        ),
    )
    annotation = DrawingAnnotation(
        uuid4(),
        view.view_id,
        "horizontal",
        (reference_for_curve(line, role="start"), reference_for_curve(line, role="end")),
        (75, 120),
    )
    return build_drawing_scene(
        DrawingState((sheet,), (view,), (annotation,)),
        sheet.sheet_id,
        {view.view_id: ProjectionResult(view.view_id, "fixture", 1, curves)},
    )
