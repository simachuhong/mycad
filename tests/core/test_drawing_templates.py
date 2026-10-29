# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Templates are self-contained paper data, replayable without a template library."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from mycad.app import build_app, new_document, open_app_document
from mycad.core.drawing import DrawingSheet, DrawingState
from mycad.core.drawing_codec import drawing_object_mapping
from mycad.core.drawing_paper import paper_texts, sheet_frame
from mycad.core.drawing_projection import LineCurve, build_drawing_scene
from mycad.core.drawing_templates import DrawingTemplate, builtin_template
from mycad.core.persistence import save_document


@pytest.mark.parametrize("standard", ["GB", "ISO"])
@pytest.mark.parametrize(
    "paper,short,long",
    [("A4", 210, 297), ("A3", 297, 420), ("A2", 420, 594), ("A1", 594, 841), ("A0", 841, 1189)],
)
@pytest.mark.parametrize("landscape", [False, True])
def test_builtin_template_physical_layout(
    standard: str, paper: str, short: int, long: int, landscape: bool
) -> None:
    template = builtin_template(standard, paper, landscape=landscape)
    assert template.size_mm == ((long, short) if landscape else (short, long))
    assert template.standard.startswith(standard)
    assert template.name
    assert {"标题", "图号", "材料", "设计", "审核", "比例", "页码"} <= {
        text.field for text in template.texts
    }
    assert len(template.curves) > 20
    assert DrawingTemplate.from_mapping(template.to_mapping()) == template
    sheet = DrawingSheet(
        uuid4(), size_mm=template.size_mm, template=template, title=(("图号", "MY-001"),)
    )
    scene = build_drawing_scene(DrawingState(sheets=(sheet,)), sheet.sheet_id, {})
    assert sheet_frame(scene) == template.curves
    assert any(t.text == "MY-001" for t in paper_texts(scene))


def test_frame_margins_and_projection_symbol() -> None:
    gb = builtin_template("GB", "A4", landscape=False)
    iso = builtin_template("ISO", "A4", landscape=False)
    assert isinstance(gb.curves[0], LineCurve)
    assert isinstance(iso.curves[0], LineCurve)
    assert gb.curves[0].start == (25, 5)
    assert iso.curves[0].start == (20, 10)
    assert (
        gb.curves != builtin_template("GB", "A4", landscape=False, projection_angle="third").curves
    )
    with pytest.raises(ValueError, match="幅面"):
        DrawingSheet(uuid4(), size_mm=(100, 100), template=gb)
    with pytest.raises(ValueError):
        DrawingTemplate.from_mapping({**gb.to_mapping(), "version": 999})
    with pytest.raises(ValueError):
        replace(gb, size_mm=(float("nan"), 100))


def test_template_archive_undo_redo_and_old_sheet(tmp_path: Path) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    sheet = DrawingSheet(uuid4())
    loaded.bus.execute("drawing.sheet.create", drawing_object_mapping(sheet), version=1)
    old = loaded.document.commands[0]
    template = builtin_template("ISO", "A4")
    loaded.bus.execute(
        "drawing.sheet.update", {"sheet_id": str(sheet.sheet_id), "template": template.to_mapping()}
    )
    state = services.kernel.drawing_state
    assert state.sheet(sheet.sheet_id).template == template
    path = tmp_path / "template.my3d"
    save_document(loaded.document, path)
    reopened = open_app_document(services, path)
    assert services.kernel.drawing_state == state
    assert reopened.document.commands[0] == old
    reopened.bus.undo()
    assert services.kernel.drawing_state.sheet(sheet.sheet_id).template is None
    reopened.bus.redo()
    assert services.kernel.drawing_state == state
