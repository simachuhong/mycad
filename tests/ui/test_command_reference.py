# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""命令速查对话框：CLI 动词 ↔ 命令 ID 的可查清单 (todo 20).

The CLI resolves short verbs (``box``), while the UI and the registry speak
command ids (``feature.box``). Users typing an id into the CLI panel hit
``unknown command verb 'feature.box'`` — this dialog makes both spellings
visible side by side.
"""

from __future__ import annotations

import pytest
from pytestqt.qtbot import QtBot

from mycad.app import AppServices, build_app, new_document
from mycad.ui.command_reference import CommandReferenceDialog, collect_rows
from mycad.ui.main_window import MainWindow


@pytest.fixture()
def services() -> AppServices:
    return build_app(discoverers=[])


def test_rows_expose_verb_command_id_and_params(services: AppServices) -> None:
    rows = collect_rows(services.registry)
    by_verb = {row.verb: row for row in rows}

    assert set(by_verb) >= {
        "box",
        "cylinder",
        "extrude",
        "revolve",
        "hole",
        "hole-pattern",
        "fillet",
        "cut",
        "intersect",
    }
    assert by_verb["cylinder"].command_id == "feature.cylinder"
    assert by_verb["hole-pattern"].command_id == "feature.hole_pattern"
    assert by_verb["cut"].command_id == "modify.boolean_cut"
    assert by_verb["intersect"].command_id == "modify.boolean_intersect"
    assert by_verb["body-boolean"].command_id == "modify.boolean_bodies"
    assert by_verb["body-transform"].command_id == "modify.body_transform"
    assert by_verb["body-pattern"].command_id == "modify.body_pattern"
    assert by_verb["cylinder"].label_zh == "圆柱体"
    assert "radius*" in by_verb["cylinder"].params
    assert "height*" in by_verb["cylinder"].params
    # Nested objects expose their child keys so the dotted CLI form is visible.
    assert "target_face*" in by_verb["hole"].params
    assert "surface" in by_verb["hole"].params


def test_dialog_lists_and_filters_rows(services: AppServices, qtbot: QtBot) -> None:
    dialog = CommandReferenceDialog(services.registry)
    qtbot.addWidget(dialog)

    assert dialog.table.rowCount() == len(collect_rows(services.registry))

    dialog.search.setText("hole")
    assert dialog.table.rowCount() == 2

    dialog.search.setText("cylinder")
    assert dialog.table.rowCount() == 1
    verb_item = dialog.table.item(0, 0)
    id_item = dialog.table.item(0, 1)
    assert verb_item is not None
    assert id_item is not None
    assert verb_item.text() == "cylinder"
    assert id_item.text() == "feature.cylinder"


def test_help_menu_action_opens_the_dialog(
    services: AppServices,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[int] = []

    class _StubDialog(CommandReferenceDialog):
        def exec(self) -> int:
            opened.append(1)
            return 0

    monkeypatch.setattr("mycad.ui.main_window.CommandReferenceDialog", _StubDialog)

    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(new_document(services))

    assert window.act_command_reference.isEnabled()
    window.act_command_reference.trigger()
    assert opened == [1]


def test_command_reference_is_disabled_without_services(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    assert not window.act_command_reference.isEnabled()
