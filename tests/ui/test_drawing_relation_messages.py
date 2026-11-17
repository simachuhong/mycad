# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Object terminology for relationship errors in independent 2D drawings."""

from uuid import uuid4

from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
from mycad.core.sketch import CircleEntity, LineEntity, Sketch, WorkPlaneFrame
from mycad.ui.cross_sketch_tangency_dialog import CrossSketchTangencyDialog
from mycad.ui.document_session import DocumentSession
from mycad.ui.execution import ExecutionResult
from mycad.ui.main_window import MainWindow
from mycad.ui.sketch_editor import SketchEditorDialog

_RECORD_EXECUTION_ERROR = "_record_execution_error"


def test_drawing_relationship_messages_do_not_imply_multiple_drawings(qtbot: QtBot) -> None:
    drawing = SketchEditorDialog(select_committed_entities=True)
    part = SketchEditorDialog(select_committed_entities=False)
    qtbot.addWidget(drawing)
    qtbot.addWidget(part)
    raw = "跨草图图元不满足有限曲线相切。"
    drawing.canvas.message = raw
    drawing.canvas.changed.emit()
    assert drawing.canvas.message == "关联对象不满足有限曲线相切。"
    assert drawing.drawing_command_bar.status.text() == drawing.canvas.message
    drawing.status_label.setText(raw)
    assert drawing.status_label.text() == drawing.canvas.message
    part.canvas.message = raw
    part.status_label.setText(raw)
    assert part.canvas.message == part.status_label.text() == raw

    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    dialog = CrossSketchTangencyDialog((first, second), ())
    qtbot.addWidget(dialog)
    dialog.complete_preview(relation, raw, success=False)
    assert dialog.status_label.text() == drawing.canvas.message


def test_background_drawing_error_uses_object_terminology(qtbot: QtBot) -> None:
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    message = "跨草图图元不满足有限曲线相切。"
    result = ExecutionResult(1, 0, "drawing-edit", None, message, message)
    getattr(window, _RECORD_EXECUTION_ERROR)(result)
    assert window.status_command.text() == "关联对象不满足有限曲线相切。"
    assert "关联对象" in window.information_tab.output.toPlainText()
