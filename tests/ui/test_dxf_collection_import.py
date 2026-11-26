# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""DXF collection import uses one verified, atomic candidate."""

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from PySide6.QtWidgets import QMessageBox
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.formats.providers.dxf_provider import write_sketches_dxf
from mycad.ui.main_window import MainWindow


def _skip_gl(*_args: object, **_kwargs: object) -> None:
    pass


def test_dxf_preview_reports_cyclic_blocks_and_imports_only_valid_group_member(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ezdxf

    from mycad.core.persistence import save_document

    document = cast("Callable[..., Any]", vars(ezdxf)["new"])("R2010", units=4)
    first = document.blocks.new("CycleA")
    second = document.blocks.new("CycleB")
    first.add_line((0, 0), (2, 0))
    second.add_line((0, 0), (3, 0))
    first.add_blockref("CycleB", (0, 0))
    second.add_blockref("CycleA", (0, 0))
    good = document.blocks.new("Good")
    good.add_line((0, 0), (4, 0))
    bad_insert = document.modelspace().add_blockref("CycleA", (0, 0))
    good_insert = document.modelspace().add_blockref("Good", (10, 0))
    document.groups.new("Mixed").set_data((bad_insert, good_insert))
    path = tmp_path / "cyclic.dxf"
    document.saveas(path)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    messages: list[str] = []

    def yes(
        _parent: object, _title: object, message: object, *_args: object, **_kwargs: object
    ) -> QMessageBox.StandardButton:
        messages.append(str(message))
        assert not loaded.document.commands
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", yes)
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_block_instances) == 1 and not unit.is_busy,
        timeout=15000,
    )
    assert len(messages) == 1 and "CycleA" in messages[0] and "组" in messages[0]
    assert [item.name for item in services.kernel.drawing_block_definitions] == ["Good"]
    instance = services.kernel.drawing_block_instances[0]
    assert services.kernel.drawing_groups[0].members == (
        DrawingObjectRef("block_instance", instance.instance_id),
    )
    after = app.drawing_collection_snapshot(services)
    assert len(loaded.document.commands) == 1
    saved = tmp_path / "cyclic-import.my2d"
    save_document(loaded.document, saved)
    reopened = app.open_app_document(services, saved)
    assert app.drawing_collection_snapshot(services) == after
    reopened.bus.undo_operation()
    assert not services.kernel.drawing_block_instances and not services.kernel.drawing_groups
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == after


def test_dxf_preview_imports_new_locked_block_layer_atomically(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ezdxf

    document = cast("Callable[..., Any]", vars(ezdxf)["new"])("R2010", units=4)
    document.layers.new("Protected").lock()
    block = document.blocks.new("LayerBlock")
    block.add_line((0, 0), (2, 0))
    instance = document.modelspace().add_blockref(
        "LayerBlock", (5, 5), dxfattribs={"layer": "Protected"}
    )
    document.groups.new("LayerGroup").set_data((instance,))
    path = tmp_path / "locked-layer.dxf"
    document.saveas(path)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    messages: list[str] = []

    def yes(
        _parent: object, _title: object, message: object, *_args: object, **_kwargs: object
    ) -> QMessageBox.StandardButton:
        messages.append(str(message))
        assert len(loaded.document.commands) == len(messages) - 1
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", yes)
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_block_instances) == 1 and not unit.is_busy,
        timeout=15000,
    )
    assert messages and "块" in messages[0] and "组" in messages[0]
    assert services.kernel.drawing_layers.get("Protected").locked
    assert len(services.kernel.drawing_groups) == 1
    assert len(loaded.document.commands) == 1
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_block_instances) == 2 and not unit.is_busy,
        timeout=15000,
    )
    assert len(messages) == 2 and "目标图层受限" in messages[-1]
    renamed = services.kernel.drawing_block_instances[-1].layer_name
    assert renamed != "Protected" and services.kernel.drawing_layers.get(renamed).locked
    assert services.kernel.drawing_layers.get("Protected").locked
    window.request_undo()
    qtbot.waitUntil(lambda: len(services.kernel.drawing_block_instances) == 1 and not unit.is_busy)
    assert len(services.kernel.drawing_groups) == 1


def test_dxf_preview_reports_existing_layer_appearance_conflict(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ezdxf

    from mycad.core.sketch_layers import SketchLayer

    document = cast("Callable[..., Any]", vars(ezdxf)["new"])("R2010", units=4)
    document.layers.new("Detail", dxfattribs={"color": 1})
    block = document.blocks.new("Appearance")
    block.add_line((0, 0), (2, 0))
    instance = document.modelspace().add_blockref(
        "Appearance", (5, 5), dxfattribs={"layer": "Detail"}
    )
    document.groups.new("AppearanceGroup").set_data((instance,))
    path = tmp_path / "layer-appearance.dxf"
    document.saveas(path)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    before = app.drawing_collection_snapshot(services)
    target_layer = SketchLayer("Detail", color_rgb=(0, 0, 255))
    layers = before.layers.add(target_layer)
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": layers.to_mapping(), "dimension_layer": before.dimension_layer},
        "local",
        version=1,
    )
    history = tuple(loaded.document.commands)
    messages: list[str] = []

    def yes(
        _parent: object, _title: object, message: object, *_args: object, **_kwargs: object
    ) -> QMessageBox.StandardButton:
        messages.append(str(message))
        assert tuple(loaded.document.commands) == history
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", yes)
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_block_instances) == 1 and not unit.is_busy,
        timeout=15000,
    )
    assert messages and "图层名称冲突" in messages[0] and "Detail" in messages[0]
    inserted = services.kernel.drawing_block_instances[0]
    assert inserted.layer_name != "Detail"
    assert services.kernel.drawing_layers.get("Detail") == target_layer
    assert services.kernel.drawing_layers.get(inserted.layer_name).color_rgb == (255, 0, 0)
    window.request_undo()
    qtbot.waitUntil(lambda: not services.kernel.drawing_block_instances and not unit.is_busy)
    assert services.kernel.drawing_layers.get("Detail") == target_layer


def test_dxf_import_preview_cancellation_keeps_document_unchanged(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    line = LineEntity(uuid4().hex, (0, 0), (1, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    definition = BlockDefinition(
        uuid4().hex, "Block", (LineEntity(uuid4().hex, (0, 0), (2, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (3, 3))
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("block_instance", instance.instance_id),), name="Group"
    )
    path = tmp_path / "mixed.dxf"
    write_sketches_dxf(
        (sketch,),
        path,
        block_definitions=(definition,),
        block_instances=(instance,),
        groups=(group,),
    )
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    messages: list[str] = []

    def no(
        _parent: object, _title: object, message: object, *_args: object, **_kwargs: object
    ) -> QMessageBox.StandardButton:
        messages.append(str(message))
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", no)
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    qtbot.waitUntil(lambda: bool(messages), timeout=15000)
    assert "块" in messages[0] and "组" in messages[0] and "不会导入" not in messages[0]
    assert loaded.document.commands == ()


def test_pure_block_import_repeated_via_dialog_is_atomic_and_reports_conflicts(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    definition = BlockDefinition(
        uuid4().hex, "Part", (LineEntity(uuid4().hex, (0, 0), (2, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (4, 5), 30, 2)
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("block_instance", instance.instance_id),), name="Assembly"
    )
    path = tmp_path / "pure-block.dxf"
    write_sketches_dxf(
        (), path, block_definitions=(definition,), block_instances=(instance,), groups=(group,)
    )
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    messages: list[str] = []

    def yes(
        _parent: object, _title: object, message: object, *_args: object, **_kwargs: object
    ) -> QMessageBox.StandardButton:
        messages.append(str(message))
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", yes)
    run = cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])
    run(window, path, unit_override=None)
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_block_instances) == 1 and not unit.is_busy,
        timeout=15000,
    )
    assert (
        len(loaded.document.commands) == 1
        and loaded.document.commands[-1].id == "drawing.objects.batch"
    )
    assert len(services.kernel.drawing_groups) == 1
    run(window, path, unit_override=None)
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_block_instances) == 2 and not unit.is_busy,
        timeout=15000,
    )
    assert len(messages) == 2 and "名称冲突" in messages[-1]
    assert (
        len(services.kernel.drawing_block_definitions) == len(services.kernel.drawing_groups) == 2
    )
    window.request_undo()
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_block_instances) == 1 and not unit.is_busy,
        timeout=15000,
    )
    assert (
        len(services.kernel.drawing_groups) == len(services.kernel.drawing_block_definitions) == 1
    )


def test_dxf_preview_reports_unsupported_block_text_and_imports_remaining_block(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ezdxf

    document = cast("Callable[..., Any]", vars(ezdxf)["new"])("R2010", units=4)
    bad = document.blocks.new("BadText")
    bad.add_line((0, 0), (2, 0))
    bad.add_text("Bad", dxfattribs={"height": 2.5, "oblique": 15})
    document.modelspace().add_blockref("BadText", (0, 0))
    good = document.blocks.new("Good")
    good.add_line((0, 0), (2, 0))
    document.modelspace().add_blockref("Good", (10, 0))
    path = tmp_path / "lossy-block.dxf"
    document.saveas(path)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    messages: list[str] = []

    def yes(
        _parent: object, _title: object, message: object, *_args: object, **_kwargs: object
    ) -> QMessageBox.StandardButton:
        messages.append(str(message))
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", yes)
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_block_instances) == 1 and not unit.is_busy,
        timeout=15000,
    )
    assert len(messages) == 1 and "BadText" in messages[0] and "文字" in messages[0]
    assert [item.name for item in services.kernel.drawing_block_definitions] == ["Good"]
    assert len(loaded.document.commands) == 1


def test_dxf_preview_reports_unicode_name_conflicts_before_import(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ezdxf

    document = cast("Callable[..., Any]", vars(ezdxf)["new"])("R2010", units=4)
    for index, name in enumerate(("Straße", "STRASSE"), start=1):
        document.layers.new(name)
        block = document.blocks.new(name)
        block.add_line((0, 0), (index, 0), dxfattribs={"layer": name})
        instance = document.modelspace().add_blockref(name, (index * 10, 0))
        document.groups.new(name).set_data((instance,))
    path = tmp_path / "unicode-conflicts.dxf"
    document.saveas(path)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    messages: list[str] = []
    command_counts: list[int] = []

    def yes(
        _parent: object, _title: object, message: object, *_args: object, **_kwargs: object
    ) -> QMessageBox.StandardButton:
        messages.append(str(message))
        command_counts.append(len(loaded.document.commands))
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", yes)
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_block_instances) == 2 and not unit.is_busy,
        timeout=15000,
    )
    assert len(messages) == 1
    assert command_counts == [0]
    assert all(label in messages[0] for label in ("块名称冲突", "组名称冲突", "图层名称冲突"))
    definitions = services.kernel.drawing_block_definitions
    assert len(definitions) == len(services.kernel.drawing_groups) == 2
    assert len({item.entities[0].layer_name.casefold() for item in definitions}) == 2
    window.request_undo()
    qtbot.waitUntil(lambda: not services.kernel.drawing_block_instances and not unit.is_busy)


def test_dxf_preview_reports_conflicting_block_text_styles_before_import(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ezdxf

    document = cast("Callable[..., Any]", vars(ezdxf)["new"])("R2010", units=4)
    for index, (name, font) in enumerate((("Straße", "first.ttf"), ("STRASSE", "second.ttf"))):
        document.styles.new(name, dxfattribs={"font": font})
        block = document.blocks.new(f"B{index}")
        block.add_text(f"T{index}", dxfattribs={"style": name})
        document.modelspace().add_blockref(f"B{index}", (index * 10, 0))
    path = tmp_path / "conflicting-fonts.dxf"
    document.saveas(path)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    messages: list[str] = []
    counts: list[int] = []

    def yes(
        _parent: object, _title: object, message: object, *_args: object, **_kwargs: object
    ) -> QMessageBox.StandardButton:
        messages.append(str(message))
        counts.append(len(loaded.document.commands))
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", yes)
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_block_instances) == 2 and not unit.is_busy,
        timeout=15000,
    )
    assert counts == [0]
    assert len(messages) == 1 and "文字样式名称冲突" in messages[0]
    snapshot = app.drawing_collection_snapshot(services)
    fonts = [
        snapshot.text_styles.get(definition.texts[0].style_id).font_file
        for definition in snapshot.block_definitions
    ]
    assert fonts == ["first.ttf", "second.ttf"]
    window.request_undo()
    qtbot.waitUntil(lambda: not services.kernel.drawing_block_instances and not unit.is_busy)


def test_dxf_preview_reports_transparent_block_layer_and_imports_other_content(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ezdxf

    document = cast("Callable[..., Any]", vars(ezdxf)["new"])("R2010", units=4)
    document.layers.new("Transparent").transparency = 0.5
    document.blocks.new("Layered").add_line((0, 0), (2, 0))
    document.modelspace().add_blockref("Layered", (0, 0), dxfattribs={"layer": "Transparent"})
    document.blocks.new("Good").add_line((0, 0), (1, 0))
    document.modelspace().add_blockref("Good", (10, 0))
    path = tmp_path / "transparent-layer.dxf"
    document.saveas(path)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    messages: list[str] = []

    def yes(
        _parent: object, _title: object, message: object, *_args: object, **_kwargs: object
    ) -> QMessageBox.StandardButton:
        messages.append(str(message))
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", yes)
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_block_instances) == 1 and not unit.is_busy,
        timeout=15000,
    )
    assert len(messages) == 1 and "Layered" in messages[0] and "透明" in messages[0]
    assert [item.name for item in services.kernel.drawing_block_definitions] == ["Good"]
    assert len(loaded.document.commands) == 1


def test_dxf_preview_reports_block_member_appearance_loss(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ezdxf

    document = cast("Callable[..., Any]", vars(ezdxf)["new"])("R2010", units=4)
    document.blocks.new("Styled").add_line((0, 0), (2, 0), dxfattribs={"color": 1})
    document.modelspace().add_blockref("Styled", (0, 0))
    document.blocks.new("Good").add_line((0, 0), (1, 0))
    document.modelspace().add_blockref("Good", (10, 0))
    path = tmp_path / "styled.dxf"
    document.saveas(path)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    messages: list[str] = []

    def yes(
        _parent: object, _title: object, message: object, *_args: object, **_kwargs: object
    ) -> QMessageBox.StandardButton:
        messages.append(str(message))
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", yes)
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_block_instances) == 1 and not unit.is_busy,
        timeout=15000,
    )
    assert len(messages) == 1 and "Styled" in messages[0] and "外观" in messages[0]
    assert [item.name for item in services.kernel.drawing_block_definitions] == ["Good"]
    assert len(loaded.document.commands) == 1


def test_dxf_import_preview_reports_clipped_instance_and_incomplete_group(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ezdxf
    from ezdxf.xclip import XClip

    document = cast("Callable[..., Any]", vars(ezdxf)["new"])("R2010", units=4)
    document.blocks.new("Symbol").add_line((0, 0), (10, 0))
    clipped = document.modelspace().add_blockref("Symbol", (0, 0))
    cast("Callable[..., None]", vars(XClip)["set_block_clipping_path"])(
        XClip(clipped), ((0, -1), (3, 1))
    )
    normal = document.modelspace().add_blockref("Symbol", (20, 0))
    document.groups.new("Instances").set_data((clipped, normal))
    path = tmp_path / "clipped.dxf"
    document.saveas(path)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    messages: list[str] = []

    def yes(
        _parent: object, _title: object, message: object, *_args: object, **_kwargs: object
    ) -> QMessageBox.StandardButton:
        messages.append(str(message))
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", yes)
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_block_instances) == 1 and not unit.is_busy,
        timeout=15000,
    )
    assert len(messages) == 1 and "裁剪" in messages[0] and "Instances" in messages[0]
    assert len(services.kernel.drawing_groups[0].members) == 1
    assert len(loaded.document.commands) == 1


def test_dxf_collection_import_rejects_candidate_when_document_changes_during_confirm(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    definition = BlockDefinition(
        uuid4().hex, "Incoming", (LineEntity(uuid4().hex, (0, 0), (1, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (2, 2))
    path = tmp_path / "stale.dxf"
    write_sketches_dxf((), path, block_definitions=(definition,), block_instances=(instance,))
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    concurrent = BlockDefinition(
        uuid4().hex, "Concurrent", (LineEntity(uuid4().hex, (0, 0), (3, 0)),), ()
    )
    errors: list[str] = []

    def yes_after_change(
        _parent: object, _title: object, _message: object, *_args: object, **_kwargs: object
    ) -> QMessageBox.StandardButton:
        loaded.bus.execute("drawing.block.create", concurrent.to_mapping(), "local")
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", yes_after_change)
    monkeypatch.setattr(window, "_show_error", errors.append)
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    qtbot.waitUntil(lambda: bool(errors) and not unit.is_busy, timeout=15000)
    assert services.kernel.drawing_block_definitions == (concurrent,)
    assert services.kernel.drawing_block_instances == ()
    assert len(loaded.document.commands) == 1


def test_dxf_collection_import_rejects_unfinished_draft_without_changes(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    definition = BlockDefinition(
        uuid4().hex, "Incoming", (LineEntity(uuid4().hex, (0, 0), (1, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (2, 2))
    path = tmp_path / "draft.dxf"
    write_sketches_dxf((), path, block_definitions=(definition,), block_instances=(instance,))
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((line,))
    errors: list[str] = []
    monkeypatch.setattr(window, "_show_error", errors.append)
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    qtbot.waitUntil(lambda: bool(errors) and not unit.is_busy, timeout=15000)
    assert "草稿" in errors[0] and tuple(editor.canvas.entities) == (line,)
    assert loaded.document.commands == () and services.kernel.drawing_block_instances == ()


def test_dxf_definition_only_import_through_preview(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    definition = BlockDefinition(
        uuid4().hex, "Unused", (LineEntity(uuid4().hex, (0, 0), (2, 0)),), ()
    )
    path = tmp_path / "definition.dxf"
    write_sketches_dxf((), path, block_definitions=(definition,))
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    messages: list[str] = []

    def yes(
        _parent: object, _title: object, message: object, *_args: object, **_kwargs: object
    ) -> QMessageBox.StandardButton:
        messages.append(str(message))
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", yes)
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_block_definitions) == 1 and not unit.is_busy,
        timeout=15000,
    )
    assert len(messages) == 1 and "1 个块定义" in messages[0]
    assert services.kernel.drawing_block_instances == () and len(loaded.document.commands) == 1
    window.request_undo()
    qtbot.waitUntil(
        lambda: not services.kernel.drawing_block_definitions and not unit.is_busy, timeout=15000
    )


def test_dxf_import_preview_reports_unrenderable_instance_and_imports_valid_group(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ezdxf

    document = cast("Callable[..., Any]", vars(ezdxf)["new"])("R2010", units=4)
    document.blocks.new("Symbol").add_line((0, 0), (10, 0))
    clipped = document.modelspace().add_blockref(
        "Symbol", (0, 0), dxfattribs={"xscale": 1e308, "yscale": 1e308, "zscale": 1e308}
    )
    normal = document.modelspace().add_blockref("Symbol", (20, 0))
    document.groups.new("Instances").set_data((clipped, normal))
    path = tmp_path / "unrenderable.dxf"
    document.saveas(path)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    messages: list[str] = []

    def yes(
        _parent: object, _title: object, message: object, *_args: object, **_kwargs: object
    ) -> QMessageBox.StandardButton:
        messages.append(str(message))
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", yes)
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_block_instances) == 1 and not unit.is_busy,
        timeout=15000,
    )
    assert len(messages) == 1 and "无法展开" in messages[0] and "Instances" in messages[0]
    assert len(services.kernel.drawing_groups[0].members) == 1
    assert len(loaded.document.commands) == 1


def test_dxf_preview_reports_nearly_uniform_instance_and_imports_valid_group(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ezdxf

    from mycad.core.persistence import save_document

    document = cast("Callable[..., Any]", vars(ezdxf)["new"])("R2010", units=4)
    document.blocks.new("Long").add_line((0, 0), (0, 1e12))
    good = document.modelspace().add_blockref("Long", (0, 0))
    bad = document.modelspace().add_blockref(
        "Long", (20, 0), dxfattribs={"xscale": 1, "yscale": 1.00000000005}
    )
    document.groups.new("Mixed").set_data((good, bad))
    path = tmp_path / "nearly-uniform.dxf"
    document.saveas(path)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    messages: list[str] = []

    def yes(
        _parent: object, _title: object, message: object, *_args: object, **_kwargs: object
    ) -> QMessageBox.StandardButton:
        messages.append(str(message))
        assert loaded.document.commands == ()
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", yes)
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_block_instances) == 1 and not unit.is_busy,
        timeout=15000,
    )
    assert len(messages) == 1 and "正等比" in messages[0] and "Mixed" in messages[0]
    assert len(services.kernel.drawing_groups[0].members) == 1
    assert len(loaded.document.commands) == 1
    saved = tmp_path / "imported.my2d"
    save_document(loaded.document, saved)
    reopened = app.open_app_document(services, saved)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_block_instances == ()
    assert services.kernel.drawing_groups == ()
    reopened.bus.redo_operation()
    assert len(services.kernel.drawing_block_instances) == 1
    assert len(services.kernel.drawing_groups[0].members) == 1


def test_dxf_preview_imports_nonunit_normal_and_reports_tilted_instance(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.drawing_blocks import expand_block
    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity

    path = (
        Path(__file__).resolve().parents[2]
        / "docs/examples/drawing-collections/external-nonunit-normal.dxf"
    )
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    messages: list[str] = []

    def yes(
        _parent: object, _title: object, message: object, *_args: object, **_kwargs: object
    ) -> QMessageBox.StandardButton:
        messages.append(str(message))
        assert len(loaded.document.commands) == len(messages) - 1
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", yes)
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_block_instances) == 1 and not unit.is_busy,
        timeout=15000,
    )
    assert len(messages) == 1 and "XY 平面" in messages[0] and "MIXED_NORMAL" in messages[0]
    assert len(services.kernel.drawing_groups[0].members) == 1
    expanded = expand_block(
        services.kernel.drawing_block_definitions[0],
        services.kernel.drawing_block_instances[0],
        services.kernel.drawing_text_styles,
    )
    assert isinstance(expanded.entities[0], CircleEntity) and expanded.entities[0].center_mm == (
        6,
        6,
    )
    assert expanded.texts[0].position_mm == (5, 4)
    first_definition = services.kernel.drawing_block_definitions[0]
    first_instance = services.kernel.drawing_block_instances[0]
    first_group = services.kernel.drawing_groups[0]
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_block_instances) == 2 and not unit.is_busy,
        timeout=15000,
    )
    assert len(messages) == 2 and "冲突" in messages[1] and "MIXED_NORMAL" in messages[1]
    second_definition = services.kernel.drawing_block_definitions[1]
    second_instance = services.kernel.drawing_block_instances[1]
    second_group = services.kernel.drawing_groups[1]
    assert second_definition.definition_id != first_definition.definition_id
    assert second_definition.name != first_definition.name
    assert second_instance.instance_id != first_instance.instance_id
    assert second_instance.definition_id == second_definition.definition_id
    assert second_group.group_id != first_group.group_id and second_group.name != first_group.name
    assert second_group.members == (
        DrawingObjectRef("block_instance", second_instance.instance_id),
    )
    second_expanded = expand_block(
        second_definition, second_instance, services.kernel.drawing_text_styles
    )
    assert isinstance(second_expanded.entities[0], CircleEntity)
    assert second_expanded.entities[0].center_mm == (6, 6)
    assert second_expanded.texts[0].position_mm == (5, 4)
    native = tmp_path / "nonunit-normal.my2d"
    save_document(loaded.document, native)
    reopened = app.open_app_document(services, native)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_block_instances == (first_instance,)
    assert services.kernel.drawing_groups == (first_group,)
    reopened.bus.redo_operation()
    assert services.kernel.drawing_block_instances == (first_instance, second_instance)
    assert services.kernel.drawing_groups == (first_group, second_group)
    reopened.bus.undo_operation()
    reopened.bus.undo_operation()
    assert services.kernel.drawing_block_instances == () and services.kernel.drawing_groups == ()


def test_dxf_preview_reports_slightly_tilted_instance_and_incomplete_group(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ezdxf

    document = cast("Callable[..., Any]", vars(ezdxf)["new"])("R2010", units=4)
    document.blocks.new("Long").add_line((0, 0), (1e12, 0))
    good = document.modelspace().add_blockref("Long", (0, 0))
    bad = document.modelspace().add_blockref(
        "Long", (20, 0), dxfattribs={"extrusion": (5e-10, 0, 1)}
    )
    document.groups.new("Mixed").set_data((good, bad))
    path = tmp_path / "tilted-instance.dxf"
    document.saveas(path)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    messages: list[str] = []

    def yes(
        _parent: object, _title: object, message: object, *_args: object, **_kwargs: object
    ) -> QMessageBox.StandardButton:
        messages.append(str(message))
        assert loaded.document.commands == ()
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", yes)
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_block_instances) == 1 and not unit.is_busy,
        timeout=15000,
    )
    assert len(messages) == 1 and "XY 平面" in messages[0] and "Mixed" in messages[0]
    assert len(services.kernel.drawing_groups[0].members) == 1
    assert len(loaded.document.commands) == 1
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not services.kernel.drawing_groups, timeout=15000)
    assert services.kernel.drawing_block_instances == ()


def test_dxf_preview_reports_subtle_spline_loss_and_imports_remaining_group(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ezdxf

    document = cast("Callable[..., Any]", vars(ezdxf)["new"])("R2010", units=4)
    spline = document.blocks.new("SubtleSpline").add_spline()
    spline.set_open_uniform([(0, 0), (1e12, 1e12), (2e12, 1e12), (3e12, 1e12), (4e12, 0)])
    spline.weights = [1, 1, 1.0000000000005, 1, 1]
    document.blocks.new("Good").add_line((0, 0), (10, 0))
    bad = document.modelspace().add_blockref("SubtleSpline", (0, 0))
    good = document.modelspace().add_blockref("Good", (20, 0))
    document.groups.new("Mixed").set_data((bad, good))
    path = tmp_path / "subtle-spline.dxf"
    document.saveas(path)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    messages: list[str] = []

    def yes(
        _parent: object, _title: object, message: object, *_args: object, **_kwargs: object
    ) -> QMessageBox.StandardButton:
        messages.append(str(message))
        assert loaded.document.commands == ()
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", yes)
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_block_instances) == 1 and not unit.is_busy,
        timeout=15000,
    )
    assert len(messages) == 1 and "样条" in messages[0] and "Mixed" in messages[0]
    assert len(services.kernel.drawing_groups[0].members) == 1
    assert len(loaded.document.commands) == 1
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not services.kernel.drawing_groups, timeout=15000)
    assert services.kernel.drawing_block_instances == ()


@pytest.mark.parametrize("short", [False, True])
def test_dxf_import_nearly_closed_ellipse_block_keeps_open_gap(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, short: bool
) -> None:
    import math

    import ezdxf

    from mycad.core.sketch import EllipseEntity

    document = cast("Callable[..., Any]", vars(ezdxf)["new"])("R2010", units=4)
    document.blocks.new("Gap").add_ellipse(
        (0, 0),
        major_axis=(1e12, 0),
        ratio=0.5,
        start_param=0,
        end_param=5e-11 if short else math.tau - 5e-10,
    )
    instance = document.modelspace().add_blockref("Gap", (0, 0))
    document.groups.new("G").set_data((instance,))
    path = tmp_path / "ellipse-gap.dxf"
    document.saveas(path)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    messages: list[str] = []

    def yes(
        _parent: object, _title: object, message: object, *_args: object, **_kwargs: object
    ) -> QMessageBox.StandardButton:
        messages.append(str(message))
        assert loaded.document.commands == ()
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", yes)
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_block_instances) == 1 and not unit.is_busy,
        timeout=15000,
    )
    ellipse = services.kernel.drawing_block_definitions[0].entities[0]
    assert isinstance(ellipse, EllipseEntity) and not ellipse.closed
    assert ellipse.point_at(1)[1] == pytest.approx(25.0 if short else -250.0, abs=0.01)
    assert len(messages) == 1 and len(services.kernel.drawing_groups[0].members) == 1
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not services.kernel.drawing_groups, timeout=15000)
    assert services.kernel.drawing_block_instances == ()


def test_dxf_preview_reports_out_of_plane_text_direction_and_imports_valid_group(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ezdxf

    document = cast("Callable[..., Any]", vars(ezdxf)["new"])("R2010", units=4)
    document.blocks.new("TiltedText").add_mtext(
        "Label",
        dxfattribs={"char_height": 1e12, "line_spacing_style": 2, "text_direction": (1, 0, 5e-10)},
    )
    document.blocks.new("Good").add_line((0, 0), (1, 0))
    bad = document.modelspace().add_blockref("TiltedText", (0, 0))
    good = document.modelspace().add_blockref("Good", (10, 0))
    document.groups.new("Mixed").set_data((bad, good))
    path = tmp_path / "tilted-text.dxf"
    document.saveas(path)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    messages: list[str] = []

    def yes(
        _parent: object, _title: object, message: object, *_args: object, **_kwargs: object
    ) -> QMessageBox.StandardButton:
        messages.append(str(message))
        assert loaded.document.commands == ()
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", yes)
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_block_instances) == 1 and not unit.is_busy,
        timeout=15000,
    )
    assert len(messages) == 1 and "方向" in messages[0] and "Mixed" in messages[0]
    assert len(services.kernel.drawing_groups[0].members) == 1
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not services.kernel.drawing_groups, timeout=15000)
    assert services.kernel.drawing_block_instances == ()


@pytest.mark.parametrize("case", ["invalid", "same_plane", "compensated"])
def test_dxf_preview_block_plane_height_preserves_valid_or_reports_loss(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    import ezdxf

    from mycad.core.persistence import save_document

    document = cast("Callable[..., Any]", vars(ezdxf)["new"])("R2010", units=4)
    valid = case != "invalid"
    block = document.blocks.new("Plane", base_point=(10, 20, 7) if valid else (0, 0, 0))
    if valid:
        height = 8 if case == "compensated" else 7
        block.add_line((10, 20, height), (15, 20, height))
        block.add_text("Label", dxfattribs={"height": 2, "insert": (10, 21, height)})
    else:
        block.add_line((0, 0, 5e-8), (5, 0, 5e-8))
    document.blocks.new("Good").add_line((0, 0), (1, 0))
    first = document.modelspace().add_blockref(
        "Plane", (0, 0, -1) if case == "compensated" else (0, 0)
    )
    second = document.modelspace().add_blockref("Good", (10, 0))
    document.groups.new("Mixed").set_data((first, second))
    path = tmp_path / f"plane-{valid}.dxf"
    document.saveas(path)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    messages: list[str] = []

    def yes(
        _parent: object, _title: object, message: object, *_args: object, **_kwargs: object
    ) -> QMessageBox.StandardButton:
        messages.append(str(message))
        assert loaded.document.commands == ()
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", yes)
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    expected = 2 if valid else 1
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_block_instances) == expected and not unit.is_busy,
        timeout=15000,
    )
    assert len(messages) == 1 and len(services.kernel.drawing_groups[0].members) == expected
    if valid:
        assert "Plane" not in messages[0] or "未导入" not in messages[0]
        definition = next(
            item for item in services.kernel.drawing_block_definitions if item.name == "Plane"
        )
        assert definition.texts[0].position_mm == (0, 1)
    else:
        assert "Plane" in messages[0] and "XY 平面" in messages[0]
    saved = tmp_path / f"plane-{valid}.my2d"
    save_document(loaded.document, saved)
    reopened = app.open_app_document(services, saved)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_block_instances == () and services.kernel.drawing_groups == ()
    reopened.bus.redo_operation()
    assert len(services.kernel.drawing_block_instances) == expected
    assert len(services.kernel.drawing_groups[0].members) == expected


def test_external_plane_preflight_manual_sample_preview(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "docs/examples/drawing-collections/external-plane-preflight.dxf"
    )
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    messages: list[str] = []

    def yes(
        _parent: object, _title: object, message: object, *_args: object, **_kwargs: object
    ) -> QMessageBox.StandardButton:
        messages.append(str(message))
        assert loaded.document.commands == ()
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", yes)
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_block_instances) == 2 and not unit.is_busy,
        timeout=15000,
    )
    assert len(messages) == 1
    assert all(
        name in messages[0]
        for name in (
            "OFF_PLANE",
            "NEAR_SCALE",
            "TILTED_TEXT",
            "SPLINE_WEIGHT",
            "PREFLIGHT_GROUP",
        )
    )
    assert {item.name for item in services.kernel.drawing_block_definitions} == {
        "BASE_PLANE",
        "COMPENSATED",
    }
    assert len(services.kernel.drawing_groups) == 1
    assert len(services.kernel.drawing_groups[0].members) == 2
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not services.kernel.drawing_groups, timeout=15000)
    assert services.kernel.drawing_block_instances == ()


def test_legacy_polyline_block_preview_imports_valid_and_reports_width(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ezdxf

    from mycad.core.sketch import PolylineEntity

    document = cast("Callable[..., Any]", vars(ezdxf)["new"])("R2010", units=4)
    good_block = document.blocks.new("LegacyGood")
    good_block.add_polyline2d([(0, 0, 0.5), (2, 0, 0), (2, 2, 0)], format="xyb", close=True)
    bad_block = document.blocks.new("LegacyWide")
    bad_block.add_polyline2d([(0, 0), (2, 0)], dxfattribs={"default_start_width": 0.2})
    good = document.modelspace().add_blockref("LegacyGood", (0, 0))
    bad = document.modelspace().add_blockref("LegacyWide", (10, 0))
    document.groups.new("LegacyGroup").set_data((good, bad))
    path = tmp_path / "legacy-preview.dxf"
    document.saveas(path)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    messages: list[str] = []

    def yes(
        _parent: object, _title: object, message: object, *_args: object, **_kwargs: object
    ) -> QMessageBox.StandardButton:
        messages.append(str(message))
        assert loaded.document.commands == ()
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", yes)
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_block_instances) == 1 and not unit.is_busy,
        timeout=15000,
    )
    assert len(messages) == 1 and "LegacyWide" in messages[0] and "LegacyGroup" in messages[0]
    polyline = services.kernel.drawing_block_definitions[0].entities[0]
    assert isinstance(polyline, PolylineEntity) and polyline.bulges == (0.5, 0, 0)
    assert len(services.kernel.drawing_groups[0].members) == 1
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not services.kernel.drawing_groups, timeout=15000)
    assert services.kernel.drawing_block_instances == ()


def test_legacy_polyline_manual_sample_preview(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "docs/examples/drawing-collections/external-legacy-polyline.dxf"
    )
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    messages: list[str] = []

    def yes(
        _parent: object, _title: object, message: object, *_args: object, **_kwargs: object
    ) -> QMessageBox.StandardButton:
        messages.append(str(message))
        assert loaded.document.commands == ()
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", yes)
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_block_instances) == 2 and not unit.is_busy,
        timeout=15000,
    )
    assert len(messages) == 1 and "LEGACY_WIDE" in messages[0] and "LEGACY_GROUP" in messages[0]
    assert {item.name for item in services.kernel.drawing_block_definitions} == {
        "LEGACY_CLOSED",
        "LEGACY_OPEN",
    }
    assert len(services.kernel.drawing_groups[0].members) == 2
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not services.kernel.drawing_groups, timeout=15000)
    assert services.kernel.drawing_block_instances == ()


def test_dxf_preview_accepts_legacy_polyline_repeated_vertex_elevation(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ezdxf

    from mycad.core.sketch import PolylineEntity

    document = cast("Callable[..., Any]", vars(ezdxf)["new"])("R2010", units=4)
    block = document.blocks.new("ElevatedVertices", base_point=(10, 20, 7))
    block.add_polyline2d(
        [(10, 20, 7), (12, 20, 7), (12, 22, 7)],
        close=True,
        dxfattribs={"elevation": (0, 0, 7)},
    )
    instance = document.modelspace().add_blockref("ElevatedVertices", (3, 4))
    document.groups.new("ElevatedGroup").set_data((instance,))
    path = tmp_path / "legacy-elevated-vertices.dxf"
    document.saveas(path)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    messages: list[str] = []

    def yes(
        _parent: object, _title: object, message: object, *_args: object, **_kwargs: object
    ) -> QMessageBox.StandardButton:
        messages.append(str(message))
        assert loaded.document.commands == ()
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", yes)
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_block_instances) == 1 and not unit.is_busy,
        timeout=15000,
    )
    assert len(messages) == 1 and "未导入" not in messages[0]
    polyline = services.kernel.drawing_block_definitions[0].entities[0]
    assert isinstance(polyline, PolylineEntity)
    assert polyline.points_mm == ((0, 0), (2, 0), (2, 2))
    assert len(services.kernel.drawing_groups[0].members) == 1
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not services.kernel.drawing_groups, timeout=15000)
    assert services.kernel.drawing_block_instances == ()


def test_modelspace_legacy_group_preview_reports_only_invalid_member(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ezdxf

    from mycad.core.sketch import PolylineEntity

    document = cast("Callable[..., Any]", vars(ezdxf)["new"])("R2010", units=4)
    model = document.modelspace()
    good = model.add_polyline2d([(0, 0, 0.5), (5, 0, 0)], format="xyb")
    bad = model.add_polyline2d([(0, 1), (5, 1)], dxfattribs={"default_start_width": 0.2})
    line = model.add_line((10, 0), (11, 0))
    document.groups.new("MixedLegacy").set_data((good, bad, line))
    path = tmp_path / "modelspace-group.dxf"
    document.saveas(path)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    messages: list[str] = []

    def yes(
        _parent: object, _title: object, message: object, *_args: object, **_kwargs: object
    ) -> QMessageBox.StandardButton:
        messages.append(str(message))
        assert loaded.document.commands == ()
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", yes)
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_groups) == 1 and not unit.is_busy, timeout=15000
    )
    assert len(messages) == 1 and "POLYLINE" in messages[0] and "MixedLegacy" in messages[0]
    assert len(services.kernel.drawing_groups[0].members) == 2
    entities = services.kernel.sketches[0].entities
    assert len(entities) == 2 and any(isinstance(item, PolylineEntity) for item in entities)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not services.kernel.drawing_groups, timeout=15000)
    assert services.kernel.sketches == ()


def test_modelspace_legacy_group_manual_sample_preview(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.sketch import PolylineEntity

    path = (
        Path(__file__).resolve().parents[2]
        / "docs/examples/drawing-collections/external-legacy-modelspace-group.dxf"
    )
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    messages: list[str] = []

    def yes(
        _parent: object, _title: object, message: object, *_args: object, **_kwargs: object
    ) -> QMessageBox.StandardButton:
        messages.append(str(message))
        assert loaded.document.commands == ()
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", yes)
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_groups) == 1 and not unit.is_busy, timeout=15000
    )
    assert len(messages) == 1 and "宽度" in messages[0] and "MIXED_LEGACY" in messages[0]
    assert len(services.kernel.drawing_groups[0].members) == 2
    entities = services.kernel.sketches[0].entities
    assert len(entities) == 2
    assert any(isinstance(item, PolylineEntity) and item.bulges == (0.5, 0.0) for item in entities)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not services.kernel.drawing_groups, timeout=15000)
    assert services.kernel.sketches == ()
