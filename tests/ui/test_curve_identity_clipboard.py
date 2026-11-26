# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Cross-document copying keeps curve identity and datum attachment independent."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QInputDialog
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
from mycad.core.geometric_tolerance_topology import prepare_curve_identity_upgrade
from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchGeometryReference
from mycad.ui.document_session import DocumentSession
from mycad.ui.main_window import MainWindow


@pytest.fixture(autouse=True)
def _clear_clipboard(qtbot: QtBot) -> Iterator[None]:
    yield
    QApplication.clipboard().clear()


def test_cross_document_copy_of_identity_curve_and_datum(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = app.build_app(discoverers=())
    session = DocumentSession()
    window = MainWindow(services=services, document_session=session)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None and session.active is not None
    source_services = session.active.services
    curve = PolylineEntity(uuid4().hex, ((0, 0), (20, 0), (20, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    app.commit_new_sketch(source_services, loaded, sketch, session_identity=0)
    record = prepare_curve_identity_upgrade(sketch, (curve.entity_id,))[0]
    loaded.bus.execute(
        "drawing.curve_identity.upgrade",
        {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "records": [record.to_mapping()],
        },
        "local",
    )
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (25, 5),
        (20, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(curve.entity_id, "vertex", 1)
        ),
    )
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    editor.canvas.selected_entity_ids = {curve.entity_id}
    tools.selected_ids, tools.selected_id, tools.selected_kind = (
        {datum.datum_id},
        datum.datum_id,
        "datum",
    )
    assert tools.copy_frame_to_clipboard()
    window.act_new_drawing.trigger()
    target = window.active_sketch_dialog()
    assert target is not None and target is not editor

    def accept_label(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "A", True

    monkeypatch.setattr(QInputDialog, "getText", accept_label)
    assert target.canvas.begin_clipboard_paste()
    QTest.mouseClick(
        target.canvas, Qt.MouseButton.LeftButton, pos=target.canvas.local_to_screen((40, 40))
    )
    assert session.active is not None
    kernel = session.active.services.kernel
    assert len(kernel.drawing_datum_identifiers) == 1, target.status_label.text()
    copied_datum = kernel.drawing_datum_identifiers[0]
    copied_entities = [entity for item in kernel.sketches for entity in item.entities]
    assert len(copied_entities) == 1 and isinstance(copied_entities[0], PolylineEntity)
    copied = copied_entities[0]
    assert copied.entity_id != curve.entity_id
    assert copied.point_ids and set(copied.point_ids).isdisjoint(record.point_ids)
    assert copied_datum.attachment is not None
    assert copied_datum.attachment.reference.entity_id == copied.entity_id
