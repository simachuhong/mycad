# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Group property editor retains a deterministic member list."""

from uuid import uuid4

from PySide6.QtWidgets import QDialogButtonBox
from pytestqt.qtbot import QtBot

from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
from mycad.ui.drawing_collections import DrawingGroupEditor


def test_group_editor_shows_readable_members_and_removes_selected_rows(qtbot: QtBot) -> None:
    geometry = DrawingObjectRef("geometry", uuid4().hex, uuid4().hex)
    dimension = DrawingObjectRef("dimension", uuid4().hex, geometry.sketch_id)
    group = DrawingGroup(uuid4().hex, (geometry, dimension))
    dialog = DrawingGroupEditor(group, ())
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog.width() >= 520
    assert dialog.member_list.item(0).text().startswith("几何")
    assert dialog.member_list.item(1).text().startswith("尺寸")
    assert geometry.object_id not in dialog.member_list.item(0).text()
    assert geometry.object_id in dialog.member_list.item(0).toolTip()
    assert "2" in dialog.member_count.text()
    dialog.member_list.item(0).setSelected(True)
    dialog.remove_members_button.click()
    assert dialog.updated_group().members == (dimension,)
    assert "1" in dialog.member_count.text()
    ok = dialog.confirm.button(QDialogButtonBox.StandardButton.Ok)
    cancel = dialog.confirm.button(QDialogButtonBox.StandardButton.Cancel)
    assert ok is not None and ok.text() == "保存"
    assert cancel is not None and cancel.text() == "取消"


def test_group_editor_shows_specific_geometry_descriptions(qtbot: QtBot) -> None:
    geometry = DrawingObjectRef("geometry", uuid4().hex, uuid4().hex)
    group = DrawingGroup(uuid4().hex, (geometry,))
    dialog = DrawingGroupEditor(group, (), member_labels={geometry: "圆"})
    qtbot.addWidget(dialog)
    assert dialog.member_list.item(0).text() == "圆 1"


def test_remove_selection_keeps_order_and_accepts_empty_group(qtbot: QtBot) -> None:
    first = DrawingObjectRef("text", uuid4().hex)
    second = DrawingObjectRef("text", uuid4().hex)
    group = DrawingGroup(uuid4().hex, (first, second))
    dialog = DrawingGroupEditor(group, (first,))
    qtbot.addWidget(dialog)
    dialog.remove_selection()
    assert dialog.updated_group().members == (second,)
    dialog.add_selection()
    assert dialog.updated_group().members == (second, first)
    empty = DrawingGroupEditor(group, (first, second))
    qtbot.addWidget(empty)
    empty.remove_selection()
    assert not empty.has_members and "解散组" in empty.message.text()
    empty.add_selection()
    assert empty.has_members and not empty.message.text()
    empty.remove_selection()
    button = empty.confirm.button(QDialogButtonBox.StandardButton.Ok)
    assert button is not None
    button.click()
    assert empty.result() == empty.DialogCode.Accepted
