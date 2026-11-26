# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Document lifecycle: new / open / save / save-as / export / close guard.

计划 todo 8 验收：
- tmp_path 往返（new→命令→save→reopen 内容一致）；
- 脏态关闭拦截（QMessageBox 保存/放弃/取消三选，monkeypatch 分支）；
- undo（geometry_rebuilt）关拦截仍现；
- 保存成功 is_dirty=False（property）；
- 导出走 formats 既有 provider（STEP/STL/DXF）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from mycad.app import build_app
from mycad.core.sketch import CircleEntity, Sketch, WorkPlaneFrame

if TYPE_CHECKING:
    from pytest import MonkeyPatch
    from pytestqt.qtbot import QtBot

    from mycad.app import AppServices

from mycad.core.persistence import LoadedDocument
from mycad.formats.providers.dxf_provider import write_sketch_dxf
from mycad.ui.dxf_output_preview import DxfOutputPreviewDialog
from mycad.ui.main_window import MainWindow

# Teardown 兜底：pytest-qt 关窗时脏态窗口会走真实三选弹窗，offscreen 下
# exec 阻塞可挂死整个进程（faulthandler 栈实证）。本 autouse patch 注册
# 最先、最后还原——单个测试自打的 _ask_save_dialog patch 注册在后、先还
# 原，运行期语义不受影响；qtbot teardown 关窗落到 "discard" 保进程可退。


pytestmark = pytest.mark.usefixtures("choose_new_part")


def _discard(self: MainWindow) -> str:
    return "discard"


@pytest.fixture(autouse=True)
def _autodiscard_close(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(MainWindow, "_ask_save_dialog", _discard)


@pytest.fixture
def services() -> AppServices:
    return build_app(discoverers=[])


def _loaded_of(window: MainWindow) -> LoadedDocument | None:
    return window.loaded_document()


def _bound(window: MainWindow) -> LoadedDocument:
    loaded = _loaded_of(window)
    assert loaded is not None
    return loaded


def _command_tuples(window: MainWindow) -> list[tuple[str, int, dict[str, object]]]:
    loaded = _loaded_of(window)
    if loaded is None:
        return []
    return [(c.id, c.ordinal, dict(c.params)) for c in loaded.document.commands]


def _new_window(services: AppServices, qtbot: QtBot) -> MainWindow:
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    return window


def _patch_save_path(monkeypatch: MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(path), ""))
    )


def _patch_open_path(monkeypatch: MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(path), ""))
    )


def _dialog_saying(choice: str) -> object:
    def reply(self: MainWindow) -> str:
        return choice

    return reply


def _patch_dialog(monkeypatch: MonkeyPatch, choice: str) -> None:
    monkeypatch.setattr(MainWindow, "_ask_save_dialog", _dialog_saying(choice))


def test_new_document_resets_state(services: AppServices, qtbot: QtBot) -> None:
    window = _new_window(services, qtbot)
    window.act_new.triggered.emit()
    assert _loaded_of(window) is not None
    assert _bound(window).document.commands == ()
    assert not _bound(window).document.is_dirty


def test_independent_drawing_new_save_and_open_roundtrip(
    services: AppServices,
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    target = tmp_path / "drawing.mc.json"
    window = _new_window(services, qtbot)
    window.act_new_drawing.triggered.emit()

    drawing = _bound(window).document
    assert drawing.document_type == "drawing2d"
    assert drawing.archive_version == 8
    assert drawing.commands == ()
    feature_actions = {action.text(): action for action in window.menu_feature.actions()}
    assert not feature_actions["拉伸"].isEnabled()
    assert feature_actions["创建草图"].isEnabled()
    assert window.command_palette is not None

    _patch_save_path(monkeypatch, target)
    window.act_save_as.triggered.emit()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["version"] == 8
    assert payload["drawing_defaults"] == {"fillet_radius": 0, "chamfer_angle": 0}
    assert payload["document_type"] == "drawing2d"

    reopened = _new_window(services, qtbot)
    _patch_open_path(monkeypatch, target)
    reopened.act_open.triggered.emit()
    unit = reopened.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy)
    assert _bound(reopened).document.document_type == "drawing2d"
    assert _bound(reopened).document.commands == ()


def test_save_roundtrip_writes_file(
    services: AppServices, qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    target = tmp_path / "flange.mc.json"
    window = _new_window(services, qtbot)
    window.act_new.triggered.emit()
    assert _loaded_of(window) is not None
    _bound(window).bus.execute("feature.box", {"size_x": 5.0, "size_y": 5.0, "size_z": 5.0}, "test")
    assert _bound(window).document.is_dirty
    _patch_save_path(monkeypatch, target)
    window.act_save.triggered.emit()
    assert target.exists()
    assert not _bound(window).document.is_dirty


@pytest.mark.parametrize("drawing,suffix", [(True, ".my2d"), (False, ".my3d")])
@pytest.mark.parametrize("name", ["零件", "零件.rev1"])
def test_save_without_native_suffix_is_visible_and_reopens(
    services: AppServices,
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    drawing: bool,
    suffix: str,
    name: str,
) -> None:
    window = _new_window(services, qtbot)
    (window.act_new_drawing if drawing else window.act_new).trigger()
    _patch_save_path(monkeypatch, tmp_path / name)
    window.act_save.trigger()
    target = tmp_path / f"{name}{suffix}"
    assert target.is_file()
    assert str(target) in window.status_command.text()
    assert str(target) in window.windowFilePath()
    assert target.name in window.windowTitle()

    def choose_open(*args: object, **_kwargs: object) -> tuple[str, str]:
        assert str(tmp_path) == args[2]
        assert f"*{suffix}" in str(args[3])
        assert "*.mc.json" in str(args[3])
        assert "所有文件 (*)" in str(args[3])
        return str(target), ""

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(choose_open))
    reopened = _new_window(services, qtbot)
    reopened.act_open.trigger()
    qtbot.waitUntil(lambda: reopened.loaded_document() is not None)
    assert _bound(reopened).document.document_type == ("drawing2d" if drawing else "part")


@pytest.mark.parametrize("drawing,suffix", [(True, ".my2d"), (False, ".my3d")])
def test_default_save_name_and_save_as_retain_directory(
    services: AppServices,
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    drawing: bool,
    suffix: str,
) -> None:
    window = _new_window(services, qtbot)
    (window.act_new_drawing if drawing else window.act_new).trigger()
    target = tmp_path / f"自定义{suffix}"
    suggestions: list[Path] = []

    def choose_save(*args: object, **_kwargs: object) -> tuple[str, str]:
        suggestions.append(Path(str(args[2])))
        return str(target), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(choose_save))
    window.act_save.trigger()
    assert suggestions[0].is_absolute()
    assert suggestions[0].suffix == suffix
    window.act_save_as.trigger()
    assert suggestions[1] == target
    assert not target.with_name(target.name + suffix).exists()


def test_suffix_completion_does_not_overwrite_without_confirmation(
    services: AppServices,
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    target = tmp_path / "existing.my3d"
    target.write_text("keep", encoding="utf-8")
    window = _new_window(services, qtbot)
    window.act_new.trigger()
    _bound(window).bus.execute("feature.box", {"size_x": 5, "size_y": 5, "size_z": 5}, "test")
    _patch_save_path(monkeypatch, tmp_path / "existing")

    def decline_overwrite(*_args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", decline_overwrite)
    window.act_save.trigger()
    assert target.read_text(encoding="utf-8") == "keep"
    assert not (tmp_path / "existing").exists()
    assert _bound(window).document.is_dirty


def test_failed_save_as_keeps_dirty_state_and_does_not_bind_path(
    services: AppServices, qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    target = tmp_path / "unwritten.mc.json"
    window = _new_window(services, qtbot)
    window.act_new.triggered.emit()
    assert _loaded_of(window) is not None
    _bound(window).bus.execute("feature.box", {"size_x": 5.0, "size_y": 5.0, "size_z": 5.0}, "test")
    save_dialog_calls: list[None] = []

    def choose_save_path(*_args: object, **_kwargs: object) -> tuple[str, str]:
        save_dialog_calls.append(None)
        return str(target), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(choose_save_path))
    errors: list[str] = []

    def collect_error(_self: MainWindow, message: str) -> None:
        errors.append(message)

    monkeypatch.setattr(MainWindow, "_show_error", collect_error)

    def fail_save(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("mycad.ui.main_window.save_document", fail_save)
    window.act_save_as.triggered.emit()

    assert not target.exists()
    assert _bound(window).document.is_dirty
    assert len(save_dialog_calls) == 1
    assert errors == ["写入失败：disk full"]

    window.act_save.triggered.emit()

    assert len(save_dialog_calls) == 2
    assert errors == ["写入失败：disk full", "写入失败：disk full"]


def test_reopen_document_preserves_history(
    services: AppServices, qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    target = tmp_path / "flange.mc.json"
    first = _new_window(services, qtbot)
    first.act_new.triggered.emit()
    assert _loaded_of(first) is not None
    _bound(first).bus.execute("feature.box", {"size_x": 6.0, "size_y": 2.0, "size_z": 3.0}, "test")
    _patch_save_path(monkeypatch, target)
    first.act_save.triggered.emit()

    second = _new_window(services, qtbot)
    _patch_open_path(monkeypatch, target)
    second.act_open.triggered.emit()
    qtbot.waitUntil(lambda: _loaded_of(second) is not None)
    assert _command_tuples(second) == [
        (
            "feature.box",
            0,
            {
                "size_x": 6.0,
                "size_y": 2.0,
                "size_z": 3.0,
                "center": [0.0, 0.0, 0.0],
                "mode": "new",
            },
        )
    ]


def test_open_broken_file_reports_without_crash(
    services: AppServices,
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    bad = tmp_path / "bad.mc.json"
    bad.write_text("{\n  broken", encoding="utf-8")
    window = _new_window(services, qtbot)
    _patch_open_path(monkeypatch, bad)
    window.act_open.triggered.emit()
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy)
    assert _loaded_of(window) is None


def test_dirty_close_blocked_then_discard_proceeds(
    services: AppServices, qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from PySide6.QtGui import QCloseEvent

    window = _new_window(services, qtbot)
    window.act_new.triggered.emit()
    assert _loaded_of(window) is not None
    _bound(window).bus.execute("feature.box", {"size_x": 5.0, "size_y": 5.0, "size_z": 5.0}, "test")

    _patch_dialog(monkeypatch, "cancel")
    event_cancel = QCloseEvent()
    window.closeEvent(event_cancel)
    assert not event_cancel.isAccepted()

    _patch_dialog(monkeypatch, "discard")
    event_discard = QCloseEvent()
    window.closeEvent(event_discard)
    assert event_discard.isAccepted()


def test_close_after_save_is_allowed(
    services: AppServices, qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from PySide6.QtGui import QCloseEvent

    target = tmp_path / "keep.mc.json"
    window = _new_window(services, qtbot)
    window.act_new.triggered.emit()
    assert _loaded_of(window) is not None
    _bound(window).bus.execute("feature.box", {"size_x": 4.0, "size_y": 4.0, "size_z": 4.0}, "test")
    _patch_save_path(monkeypatch, target)
    window.act_save.triggered.emit()
    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted()


def test_undo_marks_dirty_and_blocks_close(
    services: AppServices, qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from PySide6.QtGui import QCloseEvent

    window = _new_window(services, qtbot)
    window.act_new.triggered.emit()
    assert _loaded_of(window) is not None
    _bound(window).bus.execute("feature.box", {"size_x": 7.0, "size_y": 7.0, "size_z": 7.0}, "test")
    window.request_undo()
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy)
    assert _bound(window).document.is_dirty

    _patch_dialog(monkeypatch, "cancel")
    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted()


@pytest.mark.parametrize("suffix", ["step", "stl"])
def test_export_chunk_uses_existing_providers(
    services: AppServices,
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    suffix: str,
) -> None:
    target = tmp_path / f"part.{suffix}"
    window = _new_window(services, qtbot)
    window.act_new.triggered.emit()
    assert _loaded_of(window) is not None
    _bound(window).bus.execute("feature.box", {"size_x": 5.0, "size_y": 5.0, "size_z": 5.0}, "test")
    _patch_save_path(monkeypatch, target)
    window.act_export.triggered.emit()
    assert target.exists()
    assert target.stat().st_size > 0


@pytest.mark.parametrize("preview_action", ["accept", "cancel", "stale"])
def test_export_dxf_reports_supported_sketch_exchange(
    services: AppServices,
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    preview_action: str,
) -> None:
    target = tmp_path / "sketch.dxf"
    window = _new_window(services, qtbot)
    window.act_new.triggered.emit()
    loaded = _loaded_of(window)
    assert loaded is not None
    loaded.bus.execute(
        "sketch.create",
        Sketch(
            "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a",
            WorkPlaneFrame.xy(),
            (CircleEntity("1b1b1b1b-1b1b-4b1b-8b1b-1b1b1b1b1b1b", (0.0, 0.0), 5.0),),
        ).to_mapping(),
        "test",
    )
    _patch_save_path(monkeypatch, target)
    target.write_bytes(b"previous export")
    previews: list[bool] = []

    def inspect_preview(dialog: DxfOutputPreviewDialog) -> int:
        assert target.read_bytes() == b"previous export"
        assert dialog.renderer.isValid()
        assert "DXF AC1024" in dialog.report_label.text()
        previews.append(True)
        if preview_action == "stale":
            loaded.bus.undo()
        return int(
            dialog.DialogCode.Rejected if preview_action == "cancel" else dialog.DialogCode.Accepted
        )

    monkeypatch.setattr(DxfOutputPreviewDialog, "exec", inspect_preview)

    window.act_export.triggered.emit()
    qtbot.waitUntil(lambda: bool(previews), timeout=10000)
    if preview_action == "accept":
        assert target.read_bytes() != b"previous export"
        assert "DXF AC1024" in window.status_command.text()
        assert "导出 1 个图元" in window.status_command.text()
    else:
        assert target.read_bytes() == b"previous export"
        assert (
            "已取消" if preview_action == "cancel" else "已过期"
        ) in window.status_command.text()


@pytest.mark.parametrize("preview_action", ["accept", "cancel", "stale"])
def test_drawing2d_multi_sketch_dxf_preview_is_atomic(
    services: AppServices,
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    preview_action: str,
) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    target = tmp_path / "drawing.dxf"
    window = _new_window(services, qtbot)
    window.act_new_drawing.trigger()
    loaded = _bound(window)
    circles = (
        CircleEntity("1b" * 16, (0, 0), 2),
        CircleEntity("2c" * 16, (8, 0), 3),
    )
    for index, circle in enumerate(circles):
        sketch = Sketch(("3d" if index == 0 else "4e") * 16, WorkPlaneFrame.xy(), (circle,))
        loaded.bus.execute("sketch.create", sketch.to_state_mapping(), "test")
    _patch_save_path(monkeypatch, target)
    target.write_bytes(b"previous export")
    previews: list[bool] = []

    def inspect_preview(dialog: DxfOutputPreviewDialog) -> int:
        assert target.read_bytes() == b"previous export"
        assert dialog.renderer.isValid() and "多个草图" in dialog.report_label.text()
        previews.append(True)
        if preview_action == "stale":
            loaded.bus.undo()
        return int(
            dialog.DialogCode.Rejected if preview_action == "cancel" else dialog.DialogCode.Accepted
        )

    monkeypatch.setattr(DxfOutputPreviewDialog, "exec", inspect_preview)
    window.act_export.triggered.emit()
    qtbot.waitUntil(lambda: bool(previews), timeout=15000)
    if preview_action == "accept":
        assert read_sketch_dxf(target).sketch.entities == circles
    else:
        assert target.read_bytes() == b"previous export"
        assert (
            "已取消" if preview_action == "cancel" else "已过期"
        ) in window.status_command.text()


def test_import_dxf_previews_then_commits_through_bus(
    services: AppServices,
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    source = tmp_path / "source.dxf"
    write_sketch_dxf(
        Sketch(
            "2a2a2a2a-2a2a-4a2a-8a2a-2a2a2a2a2a2a",
            WorkPlaneFrame.xy(),
            (CircleEntity("3b3b3b3b-3b3b-4b3b-8b3b-3b3b3b3b3b3b", (0.0, 0.0), 5.0),),
        ),
        source,
    )
    _patch_open_path(monkeypatch, source)
    window = _new_window(services, qtbot)
    window.act_new.triggered.emit()
    confirmed_text: list[str] = []

    def confirm_import(
        _parent: object, _title: str, text: str, *_args: object, **_kwargs: object
    ) -> QMessageBox.StandardButton:
        loaded = _loaded_of(window)
        assert loaded is not None and loaded.document.commands == ()
        confirmed_text.append(text)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", staticmethod(confirm_import))
    assert window.act_import.isEnabled()

    window.act_import.trigger()

    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: len(_bound(window).document.commands) == 1 and not unit.is_busy)
    command = _bound(window).document.commands[0]
    assert command.id == "sketch.create"
    assert command.confirmed_by == "local"
    assert len(confirmed_text) == 1
    assert "DXF AC1024" in confirmed_text[0]
    assert "单位 mm" in confirmed_text[0]


def test_declined_dxf_preview_does_not_change_history(
    services: AppServices,
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    source = tmp_path / "source.dxf"
    write_sketch_dxf(
        Sketch(
            "4c4c4c4c-4c4c-4c4c-8c4c-4c4c4c4c4c4c",
            WorkPlaneFrame.xy(),
            (CircleEntity("5d5d5d5d-5d5d-4d5d-8d5d-5d5d5d5d5d5d", (0.0, 0.0), 5.0),),
        ),
        source,
    )
    _patch_open_path(monkeypatch, source)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *_args, **_kwargs: QMessageBox.StandardButton.No),
    )
    window = _new_window(services, qtbot)
    window.act_new.triggered.emit()

    window.act_import.trigger()

    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy)
    assert _bound(window).document.commands == ()


def test_dxf_import_requires_explicit_unit_and_scales_before_preview(
    services: AppServices,
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    source = tmp_path / "unitless.dxf"
    write_sketch_dxf(
        Sketch(
            "6e6e6e6e-6e6e-4e6e-8e6e-6e6e6e6e6e6e",
            WorkPlaneFrame.xy(),
            (CircleEntity("7f7f7f7f-7f7f-4f7f-8f7f-7f7f7f7f7f7f", (0.0, 0.0), 5.0),),
        ),
        source,
    )
    lines = source.read_text(encoding="utf-8").splitlines()
    unit_header = lines.index("$INSUNITS")
    assert lines[unit_header + 1].strip() == "70"
    lines[unit_header + 2] = "  0"
    source.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _patch_open_path(monkeypatch, source)
    monkeypatch.setattr(
        QInputDialog,
        "getItem",
        staticmethod(lambda *_args, **_kwargs: ("inch", True)),
    )
    preview_text: list[str] = []

    def confirm_import(
        _parent: object, _title: str, text: str, *_args: object, **_kwargs: object
    ) -> QMessageBox.StandardButton:
        preview_text.append(text)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", staticmethod(confirm_import))
    window = _new_window(services, qtbot)
    window.act_new.triggered.emit()

    window.act_import.trigger()

    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: len(_bound(window).document.commands) == 1 and not unit.is_busy)
    command = _bound(window).document.commands[0]
    assert command.id == "sketch.create"
    imported_entities = command.params["entities"]
    assert isinstance(imported_entities, list)
    assert imported_entities[0]["radius_mm"] == pytest.approx(127.0)
    assert "inch (override)" in preview_text[0]


@pytest.mark.parametrize("external_text", [False, True])
def test_dxf_import_restores_explicit_projection_dimension(
    services: AppServices,
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    external_text: bool,
) -> None:
    import math
    from collections.abc import Iterable
    from dataclasses import replace
    from typing import Protocol, cast
    from uuid import uuid4

    import ezdxf.filemanagement as dxf_filemanagement

    from mycad.core.persistence import save_document
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    q = math.sqrt(0.5)
    line = LineEntity(uuid4().hex, (0, 0), (20, 10))
    dimension = SketchConstraint(
        uuid4().hex,
        "distance",
        (
            SketchGeometryReference(line.entity_id, "start"),
            SketchGeometryReference(line.entity_id, "end"),
        ),
        30 * q,
        "mm",
        driving=False,
        axis="horizontal",
        projection_axis=(q, q),
    )
    source = tmp_path / "projection.dxf"
    write_sketch_dxf(Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)), source)
    if external_text:

        class MutableTextAttributes(Protocol):
            text_midpoint: tuple[float, float, float]
            dimtype: int

        class DimensionEntity(Protocol):
            dxf: MutableTextAttributes

            def dxftype(self) -> str: ...

        class DxfDocument(Protocol):
            def modelspace(self) -> Iterable[DimensionEntity]: ...

            def saveas(self, path: Path) -> None: ...

        class DxfReader(Protocol):
            def __call__(self, path: Path) -> DxfDocument: ...

        document = cast("DxfReader", vars(dxf_filemanagement)["readfile"])(source)
        native = next(item for item in document.modelspace() if item.dxftype() == "DIMENSION")
        native.dxf.text_midpoint = (35, 22, 0)
        native.dxf.dimtype |= 128
        document.saveas(source)
    _patch_open_path(monkeypatch, source)
    previews: list[str] = []

    def confirm(
        _parent: object, _title: str, text: str, *_args: object, **_kwargs: object
    ) -> QMessageBox.StandardButton:
        previews.append(text)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", staticmethod(confirm))
    window = _new_window(services, qtbot)
    window.act_new_drawing.trigger()
    window.act_import.trigger()
    unit = window.execution_unit
    assert unit is not None
    loaded = _bound(window)
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 1 and not unit.is_busy, timeout=10000)
    assert "恢复关联尺寸 1 个" in previews[0]
    if external_text:
        assert "外部文字位置已恢复" in previews[0]
    assert loaded.document.commands[-1].version == 28
    expected = replace(dimension, text_position_mm=(35, 22)) if external_text else dimension
    assert services.kernel.sketches[0].constraints == (expected,)
    after = services.kernel.sketches
    path = tmp_path / "projection.my2d"
    save_document(loaded.document, path)
    loaded.bus.undo()
    assert not services.kernel.sketches
    loaded.bus.redo()
    assert services.kernel.sketches == after
    from mycad.app import open_app_document

    reopened = build_app(discoverers=[])
    open_app_document(reopened, path)
    assert reopened.kernel.sketches == after


def test_save_without_document_is_noop(
    services: AppServices, qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    window = _new_window(services, qtbot)
    _patch_save_path(monkeypatch, Path("/tmp/never-mycad.mc.json"))
    window.act_save.triggered.emit()
    assert _loaded_of(window) is None
    assert not Path("/tmp/never-mycad.mc.json").exists()


@pytest.mark.parametrize("save_as", [False, True])
def test_save_commits_active_planar_sketch_and_keeps_drawing(
    services: AppServices,
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    save_as: bool,
) -> None:
    window = _new_window(services, qtbot)
    window.act_new_drawing.trigger()
    draft = window.active_sketch_dialog()
    assert draft is not None
    draft.canvas.set_tool("圆")
    draft.canvas.add_coordinate_point((0.0, 0.0))
    draft.canvas.add_coordinate_point((5.0, 0.0))
    target = tmp_path / "sketch.my2d"
    _patch_save_path(monkeypatch, target)

    (window.act_save_as if save_as else window.act_save).trigger()

    qtbot.waitUntil(target.exists)
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert len(payload["commands"]) == 1
    assert payload["commands"][0]["id"] == "sketch.create"
    assert payload["commands"][0]["params"]["entities"][0]["radius_mm"] == 5.0
    assert not _bound(window).document.is_dirty
    assert window.active_workspace == "sketch"
    assert window.active_sketch_dialog() is not draft
    window.act_save.trigger()
    assert len(_bound(window).document.commands) == 1


@pytest.mark.parametrize("pending", [False, True])
def test_close_active_sketch_can_cancel_or_discard(
    services: AppServices,
    qtbot: QtBot,
    monkeypatch: MonkeyPatch,
    pending: bool,
) -> None:
    from PySide6.QtGui import QCloseEvent

    window = _new_window(services, qtbot)
    window.act_new_drawing.trigger()
    draft = window.active_sketch_dialog()
    assert draft is not None
    draft.canvas.set_tool("圆")
    draft.canvas.add_coordinate_point((0.0, 0.0))
    if not pending:
        draft.canvas.add_coordinate_point((5.0, 0.0))
    _patch_dialog(monkeypatch, "cancel")
    cancel = QCloseEvent()
    window.closeEvent(cancel)
    assert not cancel.isAccepted()
    assert window.active_sketch_dialog() is draft

    _patch_dialog(monkeypatch, "discard")
    discard = QCloseEvent()
    window.closeEvent(discard)
    assert discard.isAccepted()
    assert _bound(window).document.commands == ()


def test_close_active_sketch_saves_before_closing(
    services: AppServices,
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    window = _new_window(services, qtbot)
    window.act_new_drawing.trigger()
    window.show()
    draft = window.active_sketch_dialog()
    assert draft is not None
    draft.canvas.set_tool("圆")
    draft.canvas.add_coordinate_point((0.0, 0.0))
    draft.canvas.add_coordinate_point((5.0, 0.0))
    target = tmp_path / "close.my2d"
    _patch_save_path(monkeypatch, target)
    _patch_dialog(monkeypatch, "save")

    window.close()

    qtbot.waitUntil(lambda: not window.isVisible())
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert len(payload["commands"]) == 1
    assert not _bound(window).document.is_dirty


@pytest.mark.parametrize("failure", ["cancel_path", "incomplete", "commit", "write"])
def test_failed_sketch_save_keeps_window_and_geometry(
    services: AppServices,
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    failure: str,
) -> None:
    from mycad.core.bus import CommandBus

    window = _new_window(services, qtbot)
    window.act_new_drawing.trigger()
    window.show()
    draft = window.active_sketch_dialog()
    assert draft is not None
    draft.canvas.set_tool("圆")
    draft.canvas.add_coordinate_point((0.0, 0.0))
    draft.canvas.add_coordinate_point((5.0, 0.0))
    entities = tuple(draft.canvas.entities)
    target = tmp_path / "failed.my2d"
    _patch_save_path(monkeypatch, target)
    _patch_dialog(monkeypatch, "save")
    if failure == "cancel_path":
        monkeypatch.setattr(
            QFileDialog, "getSaveFileName", staticmethod(lambda *_a, **_k: ("", ""))
        )
    elif failure == "incomplete":
        draft.canvas.add_coordinate_point((10.0, 0.0))
    else:

        def fail(*_args: object, **_kwargs: object) -> None:
            raise OSError("simulated failure")

        if failure == "commit":
            monkeypatch.setattr(CommandBus, "execute", fail)
        else:
            monkeypatch.setattr("mycad.ui.main_window.save_document", fail)

    window.close()
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy)
    assert window.isVisible()
    assert not target.exists()
    if failure == "write":
        assert services.kernel.sketches[0].entities == entities
        assert _bound(window).document.is_dirty
    else:
        assert window.active_sketch_dialog() is draft
        assert tuple(draft.canvas.entities) == entities
        assert _bound(window).document.commands == ()
    _patch_dialog(monkeypatch, "discard")


@pytest.mark.parametrize("operation", ["open", "new_drawing"])
def test_save_active_sketch_resumes_document_switch(
    services: AppServices,
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    operation: str,
) -> None:
    window = _new_window(services, qtbot)
    window.act_new_drawing.trigger()
    target = tmp_path / "current.my2d"
    _patch_save_path(monkeypatch, target)
    window.act_save.trigger()
    source = tmp_path / "empty.my2d"
    source.write_bytes(target.read_bytes())
    _patch_open_path(monkeypatch, source)
    previous = _bound(window)
    draft = window.active_sketch_dialog()
    assert draft is not None
    draft.canvas.set_tool("圆")
    draft.canvas.add_coordinate_point((0.0, 0.0))
    draft.canvas.add_coordinate_point((5.0, 0.0))
    _patch_dialog(monkeypatch, "save")

    (window.act_open if operation == "open" else window.act_new_drawing).trigger()

    qtbot.waitUntil(lambda: _bound(window) is not previous)
    assert _bound(window).document.commands == ()
    assert len(json.loads(target.read_text(encoding="utf-8"))["commands"]) == 1
