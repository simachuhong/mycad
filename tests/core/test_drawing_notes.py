# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Paper notes replay independently of source geometry and model dimensions."""

from pathlib import Path
from uuid import uuid4

import pytest

from mycad.app import build_app, new_document, open_app_document
from mycad.core.drawing_paper import paper_texts, validate_drawing_output
from mycad.core.drawing_projection import build_drawing_scene
from mycad.core.exceptions import MycadError
from mycad.core.persistence import save_document
from mycad.formats.drawing_export import export_drawing_dxf


def test_notes_roundtrip_undo_sheet_cascade_and_layout_fingerprint(tmp_path: Path) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services, document_type="drawing2d")
    sheet, note = uuid4(), uuid4()
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(sheet)})
    fingerprint = services.kernel.drawing_source_fingerprint
    text = "技术要求：\n未注倒角 C1 {原样} \\P"
    loaded.bus.execute(
        "drawing.note.create",
        {
            "note_id": str(note),
            "sheet_id": str(sheet),
            "text": text,
            "position_mm": [30, 70],
            "height_mm": 5,
        },
    )
    assert services.kernel.drawing_source_fingerprint == fingerprint
    loaded.bus.execute("drawing.note.update", {"note_id": str(note), "position_mm": [40, 80]})
    before = services.kernel.drawing_state
    scene = build_drawing_scene(before, sheet, {})
    validate_drawing_output(scene)
    assert paper_texts(scene)[0].text == text
    assert paper_texts(scene)[0].height_mm == 5
    path = tmp_path / "notes.my2d"
    save_document(loaded.document, path)
    reopened = open_app_document(services, path)
    assert services.kernel.drawing_state == before
    reopened.bus.execute("drawing.note.delete", {"note_id": str(note)})
    assert not services.kernel.drawing_state.notes
    reopened.bus.undo()
    assert services.kernel.drawing_state == before
    reopened.bus.execute("drawing.sheet.delete", {"sheet_id": str(sheet)})
    assert not services.kernel.drawing_state.notes
    reopened.bus.undo()
    assert services.kernel.drawing_state == before
    dxf = tmp_path / "notes.dxf"
    export_drawing_dxf(scene, dxf)
    from tests.formats.test_drawing_export import tags

    exported = tags(dxf)
    assert (1, "技术要求：\\P未注倒角 C1 \\{原样\\} \\\\P") in exported
    assert (40, "5.0") in exported


def test_bad_notes_leave_history_unchanged() -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services, document_type="drawing2d")
    sheet = uuid4()
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(sheet)})
    base = {
        "note_id": str(uuid4()),
        "sheet_id": str(sheet),
        "text": "说明",
        "position_mm": [20, 30],
    }
    for extra in (
        {"text": "  \n"},
        {"height_mm": 0},
        {"height_mm": -1},
        {"sheet_id": str(uuid4())},
    ):
        with pytest.raises(MycadError):
            loaded.bus.execute("drawing.note.create", {**base, **extra})
    assert len(loaded.document.commands) == 1
    assert not services.kernel.drawing_state.notes
