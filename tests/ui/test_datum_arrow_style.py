# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Datum arrow setting changes a selected annotation through the UI."""

from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import ezdxf.filemanagement
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QInputDialog
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.geometric_tolerance import DatumIdentifier
from mycad.core.persistence import save_document
from mycad.formats.dxf_preview import prepare_dxf_output_preview
from mycad.ui.main_window import MainWindow


@pytest.mark.parametrize(("label", "style"), [("空心", "open"), ("无", "none")])
@pytest.mark.parametrize("entry", ["menu", "command"])
def test_datum_arrow_style_can_be_edited_and_undone(
    qtbot: QtBot, monkeypatch: MonkeyPatch, tmp_path: Path, label: str, style: str, entry: str
) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    datum = DatumIdentifier("a" * 32, "A", (10, 10), (0, 0), layout_mode="shared")
    assert tools.execute is not None
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        pos=tools.datum_screen_bounds(datum).center().toPoint(),
    )
    assert tools.selected_id == datum.datum_id

    def choose_style(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return label, True

    monkeypatch.setattr(QInputDialog, "getItem", choose_style)
    if entry == "menu":
        assert window.act_datum_arrow_style.isEnabled()
        window.act_datum_arrow_style.trigger()
    else:
        editor.drawing_command_bar.input.setText("DATUMARROW")
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    changed = services.kernel.drawing_datum_identifiers[0]
    assert changed.arrow_style == style
    path, arrow = tools.datum_screen_path(changed)
    assert path and bool(arrow) == (style == "open")
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_datum_identifiers == (datum,), timeout=10000)
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    window.request_redo()
    qtbot.waitUntil(lambda: services.kernel.drawing_datum_identifiers == (changed,), timeout=10000)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    loaded = window.loaded_document()
    assert loaded is not None
    path = tmp_path / "datum-arrow.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (changed,)


@pytest.mark.parametrize("style", ["filled", "open", "none"])
def test_datum_arrow_style_graphic_export(qtbot: QtBot, tmp_path: Path, style: str) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    datum = DatumIdentifier(
        "a" * 32, "A", (10, 10), (0, 0), layout_mode="shared", arrow_style=style
    )
    assert tools.execute is not None
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    preview = prepare_dxf_output_preview(
        services.kernel,
        tolerance_graphics=True,
        graphic_datum_snapshots=tools.graphic_datum_export_snapshots((datum,)),
    )
    path = tmp_path / "graphic.dxf"
    preview.write(path)
    document = cast("Any", ezdxf.filemanagement).readfile(path)
    insert = next(iter(document.modelspace().query("INSERT")))
    block = document.blocks.get(insert.dxf.name)
    kinds = [entity.dxftype() for entity in block]
    assert kinds.count("SOLID") == (1 if style == "filled" else 0)
    assert kinds.count("LINE") == (8 if style == "open" else 5)


def test_graphic_export_rejects_missing_open_datum_arrow(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    datum = DatumIdentifier(
        "c" * 32, "A", (10, 10), (0, 0), layout_mode="shared", arrow_style="open"
    )
    assert tools.execute is not None
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    snapshot = tools.graphic_datum_export_snapshots((datum,))[datum.datum_id]
    with pytest.raises(ValueError, match="箭头与样式不匹配"):
        prepare_dxf_output_preview(
            services.kernel,
            tolerance_graphics=True,
            graphic_datum_snapshots={datum.datum_id: replace(snapshot, arrow=())},
        )


@pytest.mark.parametrize("method", ["command", "clipboard"])
def test_copy_datum_preserves_arrow_style(
    qtbot: QtBot, monkeypatch: MonkeyPatch, method: str
) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    datum = DatumIdentifier(
        "b" * 32, "A", (10, 10), (0, 0), layout_mode="shared", arrow_style="open"
    )
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    canvas.set_tool("选择元素")
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=tools.datum_screen_bounds(datum).center().toPoint()
    )

    def choose_name(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "B", True

    monkeypatch.setattr(QInputDialog, "getText", choose_name)
    if method == "command":
        for command in ("COPY", "0,0", "5,3"):
            editor.drawing_command_bar.input.setText(command)
            QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    else:
        canvas.setFocus()
        QTest.keyClick(canvas, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(canvas, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((15, 13)))
    copies = services.kernel.drawing_datum_identifiers
    assert len(copies) == 2 and copies[1].arrow_style == "open"
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_datum_identifiers == (datum,), timeout=10000)
