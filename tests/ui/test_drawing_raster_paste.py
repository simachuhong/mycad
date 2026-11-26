# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""External clipboard pictures in the independent 2D workspace."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.persistence import save_document
from mycad.core.sketch import LineEntity, SketchEntity
from mycad.ui.main_window import MainWindow

_TRANSFORM_POINT = "_transform_point"
_RASTER_CONTAINS = "_raster_contains"
_ACTIVATE_COMMAND_TRANSFORM = "_activate_command_transform"
_RASTER_PREVIEW = "_raster_transform_preview"
_APPLY_TRANSFORM = "_apply_transform"
_CLIPBOARD_PASTE = "_clipboard_paste"
_CLIPBOARD_MIXED_IMAGES = "_clipboard_mixed_images"
_CLIPBOARD_ANCHOR = "_clipboard_anchor"
_CURSOR = "_cursor"
_DRAW_PREVIEW = "_draw_preview"
_ON_DRAWING_MOVE = "_on_drawing_move"
_SESSION_ID = "_session_id"
_CANVAS_SCALE = "_scale"


def _line_start(entity: SketchEntity) -> tuple[float, float]:
    assert isinstance(entity, LineEntity)
    return entity.start_mm


def _reject_draft_replacement(*_args: object, **_kwargs: object) -> bool:
    return False


@pytest.mark.parametrize("with_picture", (False, True))
@pytest.mark.parametrize("operation", ("move", "scale", "rotate", "mirror"))
def test_real_saved_tangency_move(
    qtbot: QtBot, tmp_path: Path, with_picture: bool, operation: str
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import CircleEntity

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    assert canvas.replace_draft_entities((line, circle))
    setattr(canvas, _CANVAS_SCALE, 20.0)
    window.act_cross_sketch_tangency.trigger()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((1, 0)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 4)))
    qtbot.waitUntil(lambda: bool(canvas.constraints) and not unit.is_busy, timeout=10000)
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    if with_picture:
        image = QImage(8, 4, QImage.Format.Format_ARGB32)
        image.fill(QColor("red"))
        QApplication.clipboard().setImage(image)
        assert canvas.begin_clipboard_paste()
        canvas.add_coordinate_point((50, 20), exact_point=True)
        canvas.selected_raster_ids = {services.kernel.drawing_rasters[0].image_id}
    canvas.selected_entity_ids = {line.entity_id, circle.entity_id}
    canvas.begin_transform(operation, ask_mirror_erase=operation == "mirror")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    if operation == "move":
        canvas.add_coordinate_point((0, 3), exact_point=True)
    elif operation == "scale":
        assert canvas.apply_scale_factor(2)
    elif operation == "rotate":
        assert canvas.apply_rotation_angle(90)
    else:
        canvas.add_coordinate_point((0, 20), exact_point=True)
        assert canvas.confirm_mirror_erase(True)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    entity = services.kernel.sketches[0].entities[0]
    assert isinstance(entity, LineEntity)
    expected_end = {"move": (10, 3), "scale": (20, 0), "rotate": (0, 10), "mirror": (-10, 0)}
    expected_image = {
        "move": (50, 23),
        "scale": (100, 40),
        "rotate": (-20, 50),
        "mirror": (-50, 20),
    }
    assert entity.end_mm == pytest.approx(expected_end[operation]), editor.status_label.text()
    assert len(services.kernel.sketches[0].constraints) == 1
    if with_picture:
        assert services.kernel.drawing_rasters[0].origin_mm == pytest.approx(
            expected_image[operation]
        )
        window.request_undo()
        qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
        assert _line_start(services.kernel.sketches[0].entities[0]) == pytest.approx((0, 0))
        assert services.kernel.drawing_rasters[0].origin_mm == pytest.approx((50, 20))
        window.request_redo()
        qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
        loaded = window.loaded_document()
        assert loaded is not None
        path = tmp_path / "saved-tangent-picture-move.my2d"
        save_document(loaded.document, path)
        reopened = app.build_app(discoverers=[])
        app.open_app_document(reopened, path)
        restored_line = reopened.kernel.sketches[0].entities[0]
        assert isinstance(restored_line, LineEntity)
        assert restored_line.end_mm == pytest.approx(expected_end[operation])
        assert reopened.kernel.drawing_rasters[0].origin_mm == pytest.approx(
            expected_image[operation]
        )
        assert any(c.kind == "tangent" for c in reopened.kernel.sketches[0].constraints)


@pytest.mark.parametrize("paste_order", ("before", "after"))
@pytest.mark.parametrize("fail_apply", (False, True))
@pytest.mark.parametrize("operation", ("move", "scale", "rotate", "mirror"))
def test_real_mixed_tangency_move_with_picture(
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    paste_order: str,
    fail_apply: bool,
    operation: str,
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import CircleEntity, Sketch, WorkPlaneFrame

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,)), session_identity=0
    )
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    if paste_order == "before":
        assert canvas.begin_clipboard_paste()
        canvas.add_coordinate_point((50, 20), exact_point=True)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((line,))
    setattr(canvas, _CANVAS_SCALE, 20.0)
    window.act_cross_sketch_tangency.trigger()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((1, 0)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 4)))
    qtbot.waitUntil(
        lambda: len(canvas.pending_cross_tangencies) == 1 and not unit.is_busy, timeout=10000
    )
    if paste_order == "after":
        assert canvas.begin_clipboard_paste()
        canvas.add_coordinate_point((50, 20), exact_point=True)
        window.request_undo()
        qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
        assert not services.kernel.drawing_rasters and len(canvas.pending_cross_tangencies) == 1
        window.request_redo()
        qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
        assert (
            len(services.kernel.drawing_rasters) == 1 and len(canvas.pending_cross_tangencies) == 1
        )
    assert len(services.kernel.drawing_rasters) == 1, canvas.message
    image_id = services.kernel.drawing_rasters[0].image_id
    canvas.selected_entity_ids = {line.entity_id, circle.entity_id}
    canvas.selected_raster_ids = {image_id}
    if fail_apply:

        def fail(*_args: object, **_kwargs: object) -> None:
            raise ValueError("模拟草稿提交失败")

        monkeypatch.setattr(canvas, "apply_mixed_move_atomically", fail)
    canvas.begin_transform(operation, ask_mirror_erase=operation == "mirror")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    if operation == "move":
        canvas.add_coordinate_point((0, 3), exact_point=True)
    elif operation == "scale":
        assert canvas.apply_scale_factor(2)
    elif operation == "rotate":
        assert canvas.apply_rotation_angle(90)
    else:
        canvas.add_coordinate_point((0, 20), exact_point=True)
        assert canvas.confirm_mirror_erase(True)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    if fail_apply:
        assert _line_start(canvas.entities[0]) == pytest.approx((0, 0))
        assert services.kernel.drawing_rasters[0].origin_mm == pytest.approx((50, 20))
        assert len(canvas.pending_cross_tangencies) == 1
        assert "回滚" in editor.status_label.text()
        editor.finish_sketch()
        qtbot.waitUntil(
            lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
        )
        assert len(services.kernel.cross_sketch_tangencies) == 1
        return
    assert isinstance(canvas.entities[0], LineEntity)
    expected_end = {"move": (10, 3), "scale": (20, 0), "rotate": (0, 10), "mirror": (-10, 0)}
    expected_image = {
        "move": (50, 23),
        "scale": (100, 40),
        "rotate": (-20, 50),
        "mirror": (-50, 20),
    }
    assert canvas.entities[0].end_mm == pytest.approx(expected_end[operation]), (
        editor.status_label.text()
    )
    assert services.kernel.drawing_rasters[0].origin_mm == pytest.approx(expected_image[operation])
    assert len(canvas.pending_cross_tangencies) == 1
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert _line_start(canvas.entities[0]) == pytest.approx((0, 0))
    assert services.kernel.drawing_rasters[0].origin_mm == pytest.approx((50, 20))
    assert len(canvas.pending_cross_tangencies) == 1
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert isinstance(canvas.entities[0], LineEntity)
    assert canvas.entities[0].end_mm == pytest.approx(expected_end[operation])
    assert services.kernel.drawing_rasters[0].origin_mm == pytest.approx(expected_image[operation])
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    path = tmp_path / "real-mixed-tangent-move.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=[])
    app.open_app_document(reopened, path)
    assert len(reopened.kernel.cross_sketch_tangencies) == 1
    assert reopened.kernel.drawing_rasters[0].origin_mm == pytest.approx(expected_image[operation])


def test_real_draft_tangency_move_without_picture(qtbot: QtBot, tmp_path: Path) -> None:
    from uuid import uuid4

    from mycad.core.sketch import CircleEntity

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    assert canvas.replace_draft_entities((line, circle))
    setattr(canvas, _CANVAS_SCALE, 20.0)
    window.act_cross_sketch_tangency.trigger()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((1, 0)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 4)))
    qtbot.waitUntil(lambda: bool(canvas.constraints) and not unit.is_busy, timeout=10000)
    canvas.selected_entity_ids = {line.entity_id, circle.entity_id}
    canvas.begin_transform("move")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((0, 3), exact_point=True)
    assert _line_start(canvas.entities[0]) == pytest.approx((0, 3)), canvas.message
    assert len(canvas.constraints) == 1 and canvas.constraints[0].kind == "tangent"
    assert canvas.undo_last_operation()
    assert _line_start(canvas.entities[0]) == pytest.approx((0, 0))
    assert canvas.redo_last_operation()
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    path = tmp_path / "tangent-move-no-picture.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=[])
    app.open_app_document(reopened, path)
    assert any(c.kind == "tangent" for s in reopened.kernel.sketches for c in s.constraints)
    assert _line_start(reopened.kernel.sketches[0].entities[0]) == pytest.approx((0, 3))


def test_picture_and_real_draft_tangency_move(qtbot: QtBot, tmp_path: Path) -> None:
    from uuid import uuid4

    from mycad.core.sketch import CircleEntity

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((50, 20), exact_point=True)
    raster = services.kernel.drawing_rasters[0]
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    assert canvas.replace_draft_entities((line, circle))
    setattr(canvas, _CANVAS_SCALE, 20.0)
    window.act_cross_sketch_tangency.trigger()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((1, 0)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 4)))
    qtbot.waitUntil(lambda: bool(canvas.constraints) and not unit.is_busy, timeout=10000)
    assert canvas.constraints[0].kind == "tangent"
    canvas.selected_entity_ids = {line.entity_id, circle.entity_id}
    canvas.selected_raster_ids = {raster.image_id}
    canvas.begin_transform("move")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((0, 3), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert _line_start(canvas.entities[0]) == pytest.approx((0, 3)), canvas.message
    assert services.kernel.drawing_rasters[0].origin_mm == pytest.approx((50, 23))
    assert len(canvas.constraints) == 1 and canvas.constraints[0].kind == "tangent"
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert _line_start(canvas.entities[0]) == pytest.approx((0, 0))
    assert services.kernel.drawing_rasters == (raster,)
    assert len(canvas.constraints) == 1 and canvas.constraints[0].kind == "tangent"
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert _line_start(canvas.entities[0]) == pytest.approx((0, 3))
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    path = tmp_path / "real-local-tangent-move.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=[])
    app.open_app_document(reopened, path)
    assert any(c.kind == "tangent" for s in reopened.kernel.sketches for c in s.constraints)
    assert reopened.kernel.drawing_rasters[0].origin_mm == pytest.approx((50, 23))


@pytest.fixture(autouse=True)
def clear_test_clipboard(qapp: QApplication) -> Iterator[None]:
    yield
    qapp.clipboard().clear()


def test_clipboard_picture_can_be_placed_undone_and_reopened(qtbot: QtBot, tmp_path: Path) -> None:
    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor(230, 25, 40, 128))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    window.menu_edit.aboutToShow.emit()
    assert window.act_paste.isEnabled()
    window.act_paste.trigger()
    assert editor.canvas.clipboard_paste_active
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 20))
    )
    assert len(services.kernel.drawing_rasters) == 1
    inserted = services.kernel.drawing_rasters[0]
    assert QImage.fromData(inserted.png_bytes).pixelColor(0, 0).alpha() == 128
    assert inserted.pixel_size == (8, 4)
    assert inserted.origin_mm == pytest.approx((10, 20), abs=0.2)
    assert inserted.width_mm / inserted.height_mm == 2
    path = tmp_path / "picture.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_rasters == (inserted,)
    reopened.bus.undo()
    assert not services.kernel.drawing_rasters
    reopened.bus.redo()
    assert services.kernel.drawing_rasters == (inserted,)


def test_clipboard_picture_selection_copy_delete(qtbot: QtBot) -> None:
    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    editor.canvas.setFocus()
    QTest.keyClick(editor.canvas, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert editor.canvas.clipboard_paste_active
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((0, 0))
    )
    editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 10))
    )
    assert editor.canvas.selected_raster_id == services.kernel.drawing_rasters[0].image_id
    assert editor.canvas.copy_to_clipboard()
    assert QApplication.clipboard().mimeData().hasImage()
    QTest.keyClick(editor.canvas, Qt.Key.Key_Delete)
    assert not services.kernel.drawing_rasters
    window.request_undo()
    qtbot.waitUntil(lambda: len(services.kernel.drawing_rasters) == 1, timeout=10000)


def test_selected_picture_can_be_moved_and_undone(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    assert editor.canvas.begin_clipboard_paste()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((0, 0))
    )
    editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 10))
    )
    loaded = window.loaded_document()
    assert loaded is not None
    count = loaded.document.command_count
    coordinates = iter(((30.0, True), (0.0, False)))

    def get_coordinate(*_args: object) -> tuple[float, bool]:
        return next(coordinates)

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getDouble", get_coordinate)
    editor.canvas.move_selected_raster()
    assert loaded.document.command_count == count
    assert services.kernel.drawing_rasters[0].origin_mm == (0.0, 0.0)
    coordinates = iter(((30.0, True), (40.0, True)))
    editor.canvas.move_selected_raster()
    assert services.kernel.drawing_rasters[0].origin_mm == (30.0, 40.0)
    window.request_undo()
    qtbot.waitUntil(
        lambda: services.kernel.drawing_rasters[0].origin_mm == (0.0, 0.0), timeout=10000
    )
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    window.request_redo()
    qtbot.waitUntil(
        lambda: services.kernel.drawing_rasters[0].origin_mm == (30.0, 40.0), timeout=10000
    )
    path = tmp_path / "moved-picture.my2d"
    save_document(loaded.document, path)
    app.open_app_document(services, path)
    assert services.kernel.drawing_rasters[0].origin_mm == (30.0, 40.0)


def test_copy_picture_preserves_size(qtbot: QtBot) -> None:
    from dataclasses import replace

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor(20, 30, 40, 128))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    assert editor.canvas.begin_clipboard_paste()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((0, 0))
    )
    first = services.kernel.drawing_rasters[0]
    assert editor.canvas.commit_raster_edit is not None
    editor.canvas.commit_raster_edit("update", replace(first, width_mm=40, height_mm=20))
    editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 10))
    )
    assert editor.canvas.copy_to_clipboard()
    assert editor.canvas.begin_clipboard_paste()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((50, 0))
    )
    copied = services.kernel.drawing_rasters[-1]
    assert copied.image_id != first.image_id
    assert (copied.width_mm, copied.height_mm) == (40, 20)
    assert copied.png_bytes == first.png_bytes
    window.act_new_drawing.trigger()
    target = window.active_sketch_dialog()
    assert target is not None and target is not editor
    assert target.canvas.begin_clipboard_paste()
    QTest.mouseClick(
        target.canvas, Qt.MouseButton.LeftButton, pos=target.canvas.local_to_screen((0, 0))
    )
    pasted = services.kernel.drawing_rasters[0]
    assert pasted.image_id not in {first.image_id, copied.image_id}
    assert (pasted.width_mm, pasted.height_mm) == (40, 20)
    assert pasted.png_bytes == first.png_bytes


@pytest.mark.parametrize("data", [b"[]", b"[0, 1]", b"[true, 1]", b"[NaN, 1]", b"x" * 1025])
def test_picture_clipboard_rejects_invalid_size_metadata(data: bytes) -> None:
    from mycad.ui.drawing_clipboard import raster_from_clipboard_image

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    with pytest.raises(ValueError):
        raster_from_clipboard_image(image, "0", data)


def test_pasted_picture_is_selected_for_standard_transform(qtbot: QtBot) -> None:
    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    assert editor.canvas.begin_clipboard_paste()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((0, 0))
    )
    assert editor.canvas.selected_raster_id == services.kernel.drawing_rasters[0].image_id
    editor.canvas.begin_transform("scale")
    assert not editor.canvas.transform_selecting


def test_picture_standard_transforms_save_and_replay(qtbot: QtBot, tmp_path: Path) -> None:
    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 0)))
    canvas.begin_transform("scale")
    getattr(canvas, _TRANSFORM_POINT)((0, 0), commit=True)
    assert canvas.apply_scale_factor(2)
    assert services.kernel.drawing_rasters[0].width_mm == 200
    canvas.begin_transform("rotate")
    getattr(canvas, _TRANSFORM_POINT)((0, 0), commit=True)
    assert canvas.apply_rotation_angle(90)
    assert services.kernel.drawing_rasters[0].angle_deg == 90
    assert getattr(canvas, _RASTER_CONTAINS)(services.kernel.drawing_rasters[0], (-10, 10))
    canvas.begin_transform("mirror", keep_source=False)
    getattr(canvas, _TRANSFORM_POINT)((0, 0), commit=True)
    getattr(canvas, _TRANSFORM_POINT)((10, 0), commit=True)
    transformed = services.kernel.drawing_rasters[0]
    assert transformed.angle_deg == -90
    assert transformed.mirrored
    path = tmp_path / "transformed.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_rasters == (transformed,)
    reopened.bus.undo()
    assert not services.kernel.drawing_rasters[0].mirrored
    reopened.bus.redo()
    assert services.kernel.drawing_rasters == (transformed,)


def test_picture_command_first_mirror_copy_and_keyboard_delete(qtbot: QtBot) -> None:
    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("blue"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 0)))
    canvas.selected_raster_id = None
    assert getattr(editor, _ACTIVATE_COMMAND_TRANSFORM)("mirror")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 10)))
    assert canvas.selected_raster_id is not None
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    assert not canvas.transform_selecting
    getattr(canvas, _TRANSFORM_POINT)((0, 0), commit=True)
    getattr(canvas, _TRANSFORM_POINT)((10, 0), commit=True)
    assert canvas.awaiting_mirror_erase
    assert canvas.confirm_mirror_erase(False)
    assert len(services.kernel.drawing_rasters) == 2
    mirrored = services.kernel.drawing_rasters[-1]
    assert mirrored.mirrored
    assert canvas.copy_to_clipboard()
    assert canvas.begin_clipboard_paste()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 20)))
    pasted = services.kernel.drawing_rasters[-1]
    assert pasted.mirrored and pasted.angle_deg == mirrored.angle_deg
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    assert len(services.kernel.drawing_rasters) == 2


def test_picture_delete_available_in_edit_menu(qtbot: QtBot) -> None:
    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    assert editor.canvas.begin_clipboard_paste()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((0, 0))
    )
    window.menu_edit.aboutToShow.emit()
    assert window.act_delete.isEnabled()
    window.act_delete.trigger()
    assert not services.kernel.drawing_rasters


def test_picture_numeric_transform_buttons(qtbot: QtBot) -> None:
    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    assert editor.canvas.begin_clipboard_paste()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((0, 0))
    )
    editor.angle_field.setValue(45)
    editor.numeric_rotate_button.click()
    assert services.kernel.drawing_rasters[0].angle_deg == 45
    editor.mirror_keep_source_check.setChecked(False)
    editor.numeric_mirror_button.click()
    assert services.kernel.drawing_rasters[0].mirrored


def test_picture_reference_transform_target_point_previews(qtbot: QtBot) -> None:
    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 0)))
    original = services.kernel.drawing_rasters[0]
    count = loaded.document.command_count
    canvas.begin_transform("scale")
    getattr(canvas, _TRANSFORM_POINT)((0, 0), commit=True)
    assert canvas.start_scale_reference()
    assert canvas.apply_scale_length(10)
    assert canvas.start_scale_target_points()
    getattr(canvas, _TRANSFORM_POINT)((0, 0), commit=True)
    getattr(canvas, _TRANSFORM_POINT)((20, 0), commit=False)
    assert getattr(canvas, _RASTER_PREVIEW) is not None
    assert getattr(canvas, _RASTER_PREVIEW).width_mm == 200
    assert services.kernel.drawing_rasters == (original,)
    assert loaded.document.command_count == count
    getattr(canvas, _TRANSFORM_POINT)((0, 0), commit=False)
    assert getattr(canvas, _RASTER_PREVIEW) is None
    getattr(canvas, _TRANSFORM_POINT)((20, 0), commit=True)
    assert services.kernel.drawing_rasters[0].width_mm == 200
    canvas.begin_transform("rotate")
    getattr(canvas, _TRANSFORM_POINT)((0, 0), commit=True)
    assert canvas.start_rotation_reference()
    canvas.set_rotation_reference_angle(0)
    assert canvas.start_rotation_target_points()
    getattr(canvas, _TRANSFORM_POINT)((0, 0), commit=True)
    getattr(canvas, _TRANSFORM_POINT)((0, 10), commit=False)
    assert getattr(canvas, _RASTER_PREVIEW) is not None
    assert getattr(canvas, _RASTER_PREVIEW).angle_deg == pytest.approx(90)
    assert services.kernel.drawing_rasters[0].angle_deg == 0
    getattr(canvas, _TRANSFORM_POINT)((0, 0), commit=False)
    assert getattr(canvas, _RASTER_PREVIEW) is None
    getattr(canvas, _TRANSFORM_POINT)((0, 10), commit=True)
    assert services.kernel.drawing_rasters[0].angle_deg == pytest.approx(90)


def test_transform_selection_does_not_silently_mix_picture_and_line(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    line = LineEntity(uuid4().hex, (120, 0), (150, 0))
    assert canvas.replace_draft_entities((line,))
    canvas.selected_raster_id = None
    canvas.selected_entity_ids.clear()
    canvas.begin_transform("copy")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 10)))
    assert canvas.selected_raster_id is not None
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((135, 0)))
    assert canvas.selected_entity_ids == {line.entity_id}
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    assert not canvas.transform_selecting and canvas.active_transform == "copy"
    canvas.cancel_transform()
    canvas.selected_raster_id = None
    canvas.selected_entity_ids.clear()
    canvas.begin_transform("copy")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((135, 0)))
    assert canvas.selected_entity_ids == {line.entity_id}
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 10)))
    assert canvas.selected_entity_ids == {line.entity_id}
    assert canvas.selected_raster_id is not None
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    assert not canvas.transform_selecting and canvas.active_transform == "copy"
    canvas.cancel_transform()
    canvas.selected_raster_id = services.kernel.drawing_rasters[0].image_id
    assert canvas.copy_to_clipboard()
    canvas.begin_transform("scale")
    assert canvas.active_transform == "scale"


def test_picture_transform_commands_through_command_bar(qtbot: QtBot) -> None:
    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    bar = editor.drawing_command_bar.input
    for value in ("SCALE", "0,0", "2", "ROTATE", "0,0", "90"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    image_after = services.kernel.drawing_rasters[0]
    assert image_after.width_mm == 200
    assert image_after.angle_deg == 90
    for value in ("MIRROR", "0,0", "10,0", "Y"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    assert len(services.kernel.drawing_rasters) == 1
    assert services.kernel.drawing_rasters[0].mirrored
    assert services.kernel.drawing_rasters[0].angle_deg == -90


def test_picture_window_and_crossing_selection(qtbot: QtBot) -> None:
    from dataclasses import replace

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    assert canvas.commit_raster_edit is not None
    canvas.commit_raster_edit("update", replace(original, width_mm=20, height_mm=10, angle_deg=90))
    canvas.selected_raster_id = None
    for point in ((-15, 25), (5, -5)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert canvas.selected_raster_id == original.image_id
    canvas.selected_raster_id = None
    for point in ((5, 15), (-5, 5)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert canvas.selected_raster_id == original.image_id
    canvas.selected_raster_id = None
    for point in ((-12, 18), (5, 5)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert canvas.selected_raster_id is None
    canvas.begin_transform("scale")
    for point in ((-15, 25), (5, -5)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert canvas.selected_raster_id == original.image_id
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    assert not canvas.transform_selecting
    canvas.add_coordinate_point((0, 0), exact_point=True)
    assert canvas.apply_scale_factor(2)
    assert services.kernel.drawing_rasters[0].width_mm == 40


def test_picture_box_and_control_select_mixed_objects(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    line = LineEntity(uuid4().hex, (120, 0), (140, 0))
    assert canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids.clear()
    canvas.selected_raster_id = services.kernel.drawing_rasters[0].image_id
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        pos=canvas.local_to_screen((130, 0)),
    )
    assert canvas.selected_entity_ids == {line.entity_id}
    assert canvas.selected_raster_id is not None
    canvas.selected_raster_id = None
    for point in ((-10, 60), (150, -10)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert canvas.selected_entity_ids == {line.entity_id} and canvas.selected_raster_id is not None
    assert canvas.delete_selected()
    assert not canvas.entities and not services.kernel.drawing_rasters


def test_mixed_picture_and_saved_line_delete_undo_reopen(qtbot: QtBot, tmp_path: Path) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original_image = services.kernel.drawing_rasters[0]
    line = LineEntity(uuid4().hex, (120, 0), (140, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas.selected_raster_id = None
    for point in ((-10, 60), (150, -10)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert canvas.selected_entity_ids == {line.entity_id}
    assert canvas.selected_raster_ids == {original_image.image_id}
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert not services.kernel.drawing_rasters
    assert not services.kernel.sketches[0].entities
    assert loaded.document.commands[-1].version == 63
    window.request_undo()
    qtbot.waitUntil(lambda: bool(services.kernel.drawing_rasters), timeout=10000)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches == (sketch,)
    window.request_redo()
    qtbot.waitUntil(lambda: not services.kernel.drawing_rasters, timeout=10000)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    path = tmp_path / "mixed-delete.my2d"
    save_document(loaded.document, path)
    app.open_app_document(services, path)
    assert not services.kernel.drawing_rasters and not services.kernel.sketches[0].entities


def test_mixed_picture_and_saved_line_move_undo_reopen(qtbot: QtBot, tmp_path: Path) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original_image = services.kernel.drawing_rasters[0]
    line = LineEntity(uuid4().hex, (120, 0), (140, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas.selected_raster_ids = {original_image.image_id}
    canvas.selected_entity_ids = {line.entity_id}
    canvas.begin_transform("move")
    assert canvas.active_transform == "move"
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((10, 20), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.drawing_rasters[0].origin_mm == (10, 20)
    assert _line_start(services.kernel.sketches[0].entities[0]) == (130, 20)
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_rasters == (original_image,), timeout=10000)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches == (sketch,)
    window.request_redo()
    qtbot.waitUntil(lambda: services.kernel.drawing_rasters[0].origin_mm == (10, 20), timeout=10000)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    path = tmp_path / "mixed-move.my2d"
    save_document(loaded.document, path)
    app.open_app_document(services, path)
    assert services.kernel.drawing_rasters[0].origin_mm == (10, 20)
    assert _line_start(services.kernel.sketches[0].entities[0]) == (130, 20)


@pytest.mark.parametrize("selection", ("clicks", "window"))
def test_mixed_move_command_first_selection(qtbot: QtBot, selection: str) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    image_id = services.kernel.drawing_rasters[0].image_id
    line = LineEntity(uuid4().hex, (120, 0), (140, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas.selected_raster_ids.clear()
    canvas.selected_entity_ids.clear()
    canvas.begin_transform("move")
    points = ((10, 10), (130, 0)) if selection == "clicks" else ((-10, 60), (150, -10))
    for point in points:
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert canvas.selected_raster_ids == {image_id}
    assert canvas.selected_entity_ids == {line.entity_id}
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    assert not canvas.transform_selecting
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((10, 20), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.drawing_rasters[0].origin_mm == (10, 20)
    assert _line_start(services.kernel.sketches[0].entities[0]) == (130, 20)


def test_mixed_saved_scale_and_draft_guard(qtbot: QtBot, tmp_path: Path) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    line = LineEntity(uuid4().hex, (120, 0), (140, 0))
    canvas.entities = [line]
    canvas.selected_entity_ids = {line.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    canvas.entities = []
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas.selected_entity_ids = {line.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    canvas.begin_transform("scale")
    canvas.add_coordinate_point((10, 10), exact_point=True)
    assert canvas.apply_scale_factor(2)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    result = services.kernel.drawing_rasters[0]
    assert result.origin_mm == (-10, -10) and result.width_mm == original.width_mm * 2
    assert _line_start(services.kernel.sketches[0].entities[0]) == (230, -10)
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_rasters == (original,), timeout=10000)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches == (sketch,)
    window.request_redo()
    qtbot.waitUntil(
        lambda: services.kernel.drawing_rasters[0].width_mm == result.width_mm, timeout=10000
    )
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    path = tmp_path / "mixed-scale.my2d"
    save_document(loaded.document, path)
    app.open_app_document(services, path)
    assert services.kernel.drawing_rasters[0] == result
    assert _line_start(services.kernel.sketches[0].entities[0]) == (230, -10)


def test_mixed_saved_rotate_undo_reopen(qtbot: QtBot, tmp_path: Path) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    line = LineEntity(uuid4().hex, (120, 0), (140, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas.selected_entity_ids = {line.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    canvas.begin_transform("rotate")
    canvas.add_coordinate_point((10, 10), exact_point=True)
    assert canvas.apply_rotation_angle(90)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    result = services.kernel.drawing_rasters[0]
    assert result.origin_mm == pytest.approx((20, 0)) and result.angle_deg == 90
    assert _line_start(services.kernel.sketches[0].entities[0]) == pytest.approx((20, 120))
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_rasters == (original,), timeout=10000)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches == (sketch,)
    window.request_redo()
    qtbot.waitUntil(lambda: services.kernel.drawing_rasters[0].angle_deg == 90, timeout=10000)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    path = tmp_path / "mixed-rotate.my2d"
    save_document(loaded.document, path)
    app.open_app_document(services, path)
    assert services.kernel.drawing_rasters[0] == result
    assert _line_start(services.kernel.sketches[0].entities[0]) == pytest.approx((20, 120))


def test_mixed_saved_mirror_undo_reopen(qtbot: QtBot, tmp_path: Path) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    line = LineEntity(uuid4().hex, (120, 0), (140, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas.selected_entity_ids = {line.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    canvas.begin_transform("mirror", ask_mirror_erase=True)
    canvas.add_coordinate_point((10, 0), exact_point=True)
    canvas.add_coordinate_point((10, 20), exact_point=True)
    assert canvas.awaiting_mirror_erase
    assert canvas.confirm_mirror_erase(True)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    result = services.kernel.drawing_rasters[0]
    assert result.origin_mm == pytest.approx((20, 0)) and result.mirrored
    assert _line_start(services.kernel.sketches[0].entities[0]) == pytest.approx((-100, 0))
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_rasters == (original,), timeout=10000)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches == (sketch,)
    window.request_redo()
    qtbot.waitUntil(lambda: services.kernel.drawing_rasters[0].mirrored, timeout=10000)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    path = tmp_path / "mixed-mirror.my2d"
    save_document(loaded.document, path)
    app.open_app_document(services, path)
    assert services.kernel.drawing_rasters[0] == result
    assert _line_start(services.kernel.sketches[0].entities[0]) == pytest.approx((-100, 0))


def test_mixed_mirror_copy_undo_reopen(qtbot: QtBot, tmp_path: Path) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    line = LineEntity(uuid4().hex, (120, 0), (140, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas.selected_entity_ids = {line.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    canvas.begin_transform("mirror", ask_mirror_erase=True)
    canvas.add_coordinate_point((10, 0), exact_point=True)
    canvas.add_coordinate_point((10, 20), exact_point=True)
    assert canvas.confirm_mirror_erase(False)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert len(services.kernel.drawing_rasters) == 2
    assert services.kernel.drawing_rasters[0] == original
    assert services.kernel.drawing_rasters[1].origin_mm == pytest.approx((20, 0))
    entities = services.kernel.sketches[0].entities
    assert len(entities) == 2 and entities[0] == line
    assert _line_start(entities[1]) == pytest.approx((-100, 0))
    window.request_undo()
    qtbot.waitUntil(lambda: len(services.kernel.drawing_rasters) == 1, timeout=10000)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches == (sketch,)
    window.request_redo()
    qtbot.waitUntil(lambda: len(services.kernel.drawing_rasters) == 2, timeout=10000)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    path = tmp_path / "mixed-mirror-copy.my2d"
    save_document(loaded.document, path)
    app.open_app_document(services, path)
    assert len(services.kernel.drawing_rasters) == 2
    assert services.kernel.sketches[0].entities == entities


def test_mixed_single_copy_undo_reopen(qtbot: QtBot, tmp_path: Path) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    line = LineEntity(uuid4().hex, (120, 0), (140, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas.selected_entity_ids = {line.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    canvas.set_copy_mode(1)
    canvas.begin_transform("copy")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((10, 20), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert len(services.kernel.drawing_rasters) == 2
    assert services.kernel.drawing_rasters[0] == original
    assert services.kernel.drawing_rasters[1].origin_mm == (10, 20)
    entities = services.kernel.sketches[0].entities
    assert len(entities) == 2 and entities[0] == line
    assert _line_start(entities[1]) == (130, 20)
    window.request_undo()
    qtbot.waitUntil(lambda: len(services.kernel.drawing_rasters) == 1, timeout=10000)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches == (sketch,)
    window.request_redo()
    qtbot.waitUntil(lambda: len(services.kernel.drawing_rasters) == 2, timeout=10000)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    path = tmp_path / "mixed-copy.my2d"
    save_document(loaded.document, path)
    app.open_app_document(services, path)
    assert len(services.kernel.drawing_rasters) == 2
    assert services.kernel.sketches[0].entities == entities


def test_mixed_repeated_copy_command_undo(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    line = LineEntity(uuid4().hex, (120, 0), (140, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas.selected_entity_ids = {line.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    canvas.set_copy_mode(0)
    canvas.begin_transform("copy")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    for point, count in (((10, 20), 2), ((30, 40), 3)):
        canvas.add_coordinate_point(point, exact_point=True)
        qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
        assert len(services.kernel.drawing_rasters) == count
        assert len(services.kernel.sketches[0].entities) == count
        assert canvas.active_transform == "copy"
    for count in (2, 1):
        assert canvas.undo_copy_placement()
        qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
        assert len(services.kernel.drawing_rasters) == count
        assert len(services.kernel.sketches[0].entities) == count
        assert canvas.active_transform == "copy"
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    assert canvas.active_transform is None
    assert services.kernel.drawing_rasters == (original,) and services.kernel.sketches == (sketch,)


def test_mixed_clipboard_cross_drawing_undo_reopen(qtbot: QtBot, tmp_path: Path) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    source, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert source is not None and loaded is not None and unit is not None
    canvas = source.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    line = LineEntity(uuid4().hex, (120, 0), (140, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    source.set_context_sketches(services.kernel.sketches)
    canvas.selected_entity_ids = {line.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    window.menu_edit.aboutToShow.emit()
    assert window.act_copy.isEnabled()
    window.act_copy.trigger()
    window.act_new_drawing.trigger()
    target, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert target is not None and loaded is not None and target is not source
    window.menu_edit.aboutToShow.emit()
    assert window.act_paste.isEnabled()
    window.act_paste.trigger()
    assert target.canvas.clipboard_paste_active
    target.canvas.add_coordinate_point((200, 50), exact_point=True)
    assert len(services.kernel.sketches) == 1 and len(services.kernel.drawing_rasters) == 1
    pasted = services.kernel.sketches[0].entities[0]
    copied_image = services.kernel.drawing_rasters[0]
    assert _line_start(pasted) == (200, 50) and pasted.entity_id != line.entity_id
    assert copied_image.origin_mm == (80, 50) and copied_image.image_id != original.image_id
    assert (
        loaded.document.commands[-1].id == "sketch.create"
        and loaded.document.commands[-1].version == 56
    )
    window.request_undo()
    qtbot.waitUntil(lambda: not services.kernel.drawing_rasters, timeout=10000)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert not services.kernel.sketches
    window.request_redo()
    qtbot.waitUntil(lambda: bool(services.kernel.drawing_rasters), timeout=10000)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    path = tmp_path / "mixed-paste.my2d"
    save_document(loaded.document, path)
    app.open_app_document(services, path)
    assert services.kernel.sketches[0].entities[0] == pasted
    assert services.kernel.drawing_rasters == (copied_image,)


def test_mixed_paste_imports_layer_atomically(qtbot: QtBot, tmp_path: Path) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_layers import SketchLayer

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    source, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert source is not None and loaded is not None and unit is not None
    source.request_layer_update(source.layer_table.add(SketchLayer("PARTS")), ".")
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    canvas = source.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    assert canvas.commit_raster_edit is not None
    canvas.commit_raster_edit("update", replace(original, layer_name="PARTS"))
    line = LineEntity(uuid4().hex, (120, 0), (140, 0), layer_name="PARTS")
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), layers=source.layer_table)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    source.set_context_sketches(services.kernel.sketches)
    canvas.selected_entity_ids = {line.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    assert canvas.copy_to_clipboard()
    window.act_new_drawing.trigger()
    target, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert target is not None and loaded is not None and target is not source
    with pytest.raises(KeyError):
        services.kernel.drawing_layers.get("PARTS")
    assert target.canvas.begin_clipboard_paste()
    target.canvas.add_coordinate_point((200, 50), exact_point=True)
    assert services.kernel.drawing_layers.get("PARTS").name == "PARTS"
    assert services.kernel.sketches[0].entities[0].layer_name == "PARTS"
    assert services.kernel.drawing_rasters[0].layer_name == "PARTS"
    window.request_undo()
    qtbot.waitUntil(lambda: not services.kernel.drawing_rasters, timeout=10000)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    with pytest.raises(KeyError):
        services.kernel.drawing_layers.get("PARTS")
    window.request_redo()
    qtbot.waitUntil(lambda: bool(services.kernel.drawing_rasters), timeout=10000)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    path = tmp_path / "mixed-layer.my2d"
    save_document(loaded.document, path)
    app.open_app_document(services, path)
    assert services.kernel.drawing_layers.get("PARTS").name == "PARTS"
    assert services.kernel.drawing_rasters[0].layer_name == "PARTS"


@pytest.mark.parametrize("fit", (False, True))
def test_mixed_copy_array_single_history(qtbot: QtBot, tmp_path: Path, fit: bool) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    line = LineEntity(uuid4().hex, (120, 0), (140, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas.selected_entity_ids = {line.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    canvas.set_copy_mode(0)
    canvas.begin_transform("copy")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    assert canvas.begin_copy_array()
    canvas.set_copy_array_count(3)
    if fit:
        canvas.set_copy_array_fit()
    canvas.add_coordinate_point((20 if fit else 10, 0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert [item.origin_mm for item in services.kernel.drawing_rasters] == [
        (0, 0),
        (10, 0),
        (20, 0),
    ]
    entities = services.kernel.sketches[0].entities
    assert [_line_start(item) for item in entities] == [(120, 0), (130, 0), (140, 0)]
    path = tmp_path / "mixed-array.my2d"
    save_document(loaded.document, path)
    assert canvas.undo_copy_placement()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.drawing_rasters == (original,) and services.kernel.sketches == (sketch,)
    app.open_app_document(services, path)
    assert len(services.kernel.drawing_rasters) == 3
    assert services.kernel.sketches[0].entities == entities


@pytest.mark.parametrize("operation", ("move", "copy", "rotate", "mirror"))
def test_mixed_numeric_transform_buttons(qtbot: QtBot, operation: str) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    line = LineEntity(uuid4().hex, (120, 0), (140, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas.selected_entity_ids = {line.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    editor.delta_u_field.setValue(10)
    editor.delta_v_field.setValue(20)
    editor.angle_field.setValue(90)
    buttons = {
        "move": editor.numeric_move_button,
        "copy": editor.numeric_copy_button,
        "rotate": editor.numeric_rotate_button,
        "mirror": editor.numeric_mirror_button,
    }
    buttons[operation].click()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    images, entities = services.kernel.drawing_rasters, services.kernel.sketches[0].entities
    if operation == "move":
        assert images[0].origin_mm == (10, 20) and _line_start(entities[0]) == (130, 20)
    elif operation == "copy":
        assert len(images) == 2 and images[1].origin_mm == (10, 20)
        assert len(entities) == 2 and _line_start(entities[1]) == (130, 20)
    elif operation == "rotate":
        assert images[0].angle_deg == 90 and _line_start(entities[0]) == pytest.approx((0, 120))
    else:
        assert len(images) == 2 and images[1].mirrored and len(entities) == 2
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.drawing_rasters == (original,) and services.kernel.sketches == (sketch,)


def test_mixed_numeric_offset_refuses_partial_operation(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    line = LineEntity(uuid4().hex, (120, 0), (140, 0))
    assert canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    getattr(editor, _APPLY_TRANSFORM)("offset")
    assert "图片暂不支持" in canvas.message
    assert canvas.entities == [line] and services.kernel.drawing_rasters == (original,)


def test_mixed_paste_preview_shows_image_on_unimported_layer(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtGui import QPainter

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
    from mycad.ui.drawing_clipboard import raster_from_clipboard_image
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    canvas = editor.canvas
    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    raster = raster_from_clipboard_image(image, "PARTS")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0), layer_name="PARTS")
    sketch = Sketch(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        (line,),
        layers=SketchLayerTable().add(SketchLayer("PARTS")),
    )
    setattr(canvas, _CLIPBOARD_PASTE, sketch)
    setattr(canvas, _CLIPBOARD_MIXED_IMAGES, (raster,))
    setattr(canvas, _CLIPBOARD_ANCHOR, (0.0, 0.0))
    setattr(canvas, _CURSOR, (0.0, 0.0))
    surface = QImage(canvas.size(), QImage.Format.Format_ARGB32)
    surface.fill(Qt.GlobalColor.transparent)
    painter = QPainter(surface)
    try:
        getattr(canvas, _DRAW_PREVIEW)(painter)
    finally:
        painter.end()
    sample = canvas.local_to_screen((20, 20))
    assert surface.pixelColor(sample).red() > 200
    assert surface.pixelColor(sample).alpha() > 0


@pytest.mark.parametrize("entry", ("command", "numeric"))
def test_unsaved_drawing_mixed_draft_move_undo_redo(qtbot: QtBot, entry: str) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    line = LineEntity(uuid4().hex, (120, 0), (140, 0))
    assert canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    if entry == "command":
        canvas.begin_transform("move")
        canvas.add_coordinate_point((0, 0), exact_point=True)
        canvas.add_coordinate_point((10, 20), exact_point=True)
    else:
        editor.delta_u_field.setValue(10)
        editor.delta_v_field.setValue(20)
        editor.numeric_move_button.click()
    assert _line_start(canvas.entities[0]) == (130, 20)
    assert services.kernel.drawing_rasters[0].origin_mm == (10, 20)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert canvas.entities == [line] and services.kernel.drawing_rasters == (original,)
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert _line_start(canvas.entities[0]) == (130, 20)
    assert services.kernel.drawing_rasters[0].origin_mm == (10, 20)


@pytest.mark.parametrize("operation", ("scale", "rotate", "numeric_rotate"))
def test_unsaved_mixed_draft_affine_undo_redo(qtbot: QtBot, operation: str) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    line = LineEntity(uuid4().hex, (120, 0), (140, 0))
    assert canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    if operation == "numeric_rotate":
        editor.angle_field.setValue(90)
        editor.numeric_rotate_button.click()
    else:
        canvas.begin_transform(operation)
        canvas.add_coordinate_point((0, 0), exact_point=True)
        if operation == "scale":
            assert canvas.apply_scale_factor(2)
        else:
            assert canvas.apply_rotation_angle(90)
    if operation == "scale":
        assert _line_start(canvas.entities[0]) == (240, 0)
        assert services.kernel.drawing_rasters[0].width_mm == 2 * original.width_mm
    else:
        assert _line_start(canvas.entities[0]) == pytest.approx((0, 120))
        assert services.kernel.drawing_rasters[0].angle_deg == 90
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert canvas.entities == [line] and services.kernel.drawing_rasters == (original,)
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    if operation == "scale":
        assert _line_start(canvas.entities[0]) == (240, 0)
        assert services.kernel.drawing_rasters[0].width_mm == 2 * original.width_mm
    else:
        assert _line_start(canvas.entities[0]) == pytest.approx((0, 120))
        assert services.kernel.drawing_rasters[0].angle_deg == 90


@pytest.mark.parametrize("keep_source", (False, True))
def test_unsaved_mixed_draft_mirror_undo_redo(qtbot: QtBot, keep_source: bool) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    line = LineEntity(uuid4().hex, (120, 0), (140, 0))
    assert canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    canvas.begin_transform("mirror", ask_mirror_erase=True)
    canvas.add_coordinate_point((10, 0), exact_point=True)
    canvas.add_coordinate_point((10, 20), exact_point=True)
    assert canvas.confirm_mirror_erase(not keep_source)

    def check_result() -> None:
        assert len(canvas.entities) == 1 + int(keep_source)
        assert _line_start(canvas.entities[-1]) == pytest.approx((-100, 0))
        images = services.kernel.drawing_rasters
        assert len(images) == 1 + int(keep_source)
        mirrored = next(item for item in images if item.mirrored)
        assert mirrored.origin_mm == pytest.approx((20, 0))

    check_result()
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert canvas.entities == [line] and services.kernel.drawing_rasters == (original,)
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    check_result()


def test_unsaved_mixed_draft_delete_undo_redo(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    line = LineEntity(uuid4().hex, (120, 0), (140, 0))
    assert canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    assert canvas.delete_selected()
    assert not canvas.entities and not services.kernel.drawing_rasters
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert canvas.entities == [line] and services.kernel.drawing_rasters == (original,)
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert not canvas.entities and not services.kernel.drawing_rasters


@pytest.mark.parametrize("numeric", (False, True))
def test_unsaved_mixed_draft_copy_undo_redo(qtbot: QtBot, numeric: bool) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    line = LineEntity(uuid4().hex, (120, 0), (140, 0))
    assert canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    if numeric:
        editor.delta_u_field.setValue(10)
        getattr(editor, _APPLY_TRANSFORM)("copy")
    else:
        canvas.set_copy_mode(1)
        canvas.begin_transform("copy")
        canvas.add_coordinate_point((0, 0), exact_point=True)
        canvas.add_coordinate_point((10, 0), exact_point=True)
    assert len(canvas.entities) == 2 and _line_start(canvas.entities[1]) == (130, 0)
    assert len(services.kernel.drawing_rasters) == 2
    assert any(item.origin_mm == (10, 0) for item in services.kernel.drawing_rasters)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert canvas.entities == [line] and services.kernel.drawing_rasters == (original,)
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert len(canvas.entities) == 2 and len(services.kernel.drawing_rasters) == 2


def test_unsaved_mixed_draft_repeated_copy_command_undo(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    line = LineEntity(uuid4().hex, (120, 0), (140, 0))
    assert canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    canvas.begin_transform("copy")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((10, 0), exact_point=True)
    canvas.add_coordinate_point((20, 0), exact_point=True)
    assert canvas.active_transform == "copy"
    assert len(canvas.entities) == len(services.kernel.drawing_rasters) == 3
    assert [_line_start(item) for item in canvas.entities] == [(120, 0), (130, 0), (140, 0)]
    for expected in (2, 1):
        assert canvas.undo_copy_placement()
        qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
        assert len(canvas.entities) == len(services.kernel.drawing_rasters) == expected
        assert canvas.active_transform == "copy"
    assert canvas.entities == [line] and services.kernel.drawing_rasters == (original,)
    canvas.add_coordinate_point((30, 0), exact_point=True)
    assert _line_start(canvas.entities[-1]) == (150, 0)
    canvas.cancel_transform()
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert canvas.entities == [line] and services.kernel.drawing_rasters == (original,)
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert len(canvas.entities) == len(services.kernel.drawing_rasters) == 2


@pytest.mark.parametrize("fit", (False, True))
def test_unsaved_mixed_draft_copy_array(qtbot: QtBot, fit: bool) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    line = LineEntity(uuid4().hex, (120, 0), (140, 0))
    assert canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    canvas.begin_transform("copy")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    assert canvas.begin_copy_array()
    canvas.set_copy_array_count(3)
    if fit:
        canvas.set_copy_array_fit()
    canvas.add_coordinate_point((20 if fit else 10, 0), exact_point=True)
    assert [_line_start(item) for item in canvas.entities] == [(120, 0), (130, 0), (140, 0)]
    assert sorted(item.origin_mm for item in services.kernel.drawing_rasters) == [
        (0, 0),
        (10, 0),
        (20, 0),
    ]
    assert canvas.undo_copy_placement()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert canvas.entities == [line] and services.kernel.drawing_rasters == (original,)


def test_unsaved_mixed_copy_rejects_missing_draft_history(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    line = LineEntity(uuid4().hex, (120, 0), (140, 0))
    assert canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    canvas.selected_raster_ids = {services.kernel.drawing_rasters[0].image_id}
    canvas.begin_transform("copy")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((10, 0), exact_point=True)
    count = loaded.document.command_count
    del editor.mixed_draft_history[count]
    assert canvas.undo_copy_placement()
    assert loaded.document.command_count == count
    assert len(canvas.entities) == len(services.kernel.drawing_rasters) == 2
    assert "不能撤销" in editor.status_label.text()


def test_unsaved_mixed_draft_delete_dependent_constraints(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    line = LineEntity(uuid4().hex, (120, 0), (140, 0))
    other = LineEntity(uuid4().hex, (160, 0), (180, 0))
    assert canvas.replace_draft_entities((line, other))
    dimension = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(line.entity_id, "geometry"),), 20, "mm"
    )
    independent = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(other.entity_id, "start"),)
    )
    canvas.constraints = [dimension, independent]
    canvas.selected_entity_ids = {line.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    canvas.selected_constraint_ids = {dimension.constraint_id}
    assert canvas.delete_selected()
    assert canvas.entities == [other] and canvas.constraints == [independent]
    assert not services.kernel.drawing_rasters
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert canvas.entities == [line, other] and canvas.constraints == [dimension, independent]
    assert services.kernel.drawing_rasters == (original,)
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert canvas.entities == [other] and canvas.constraints == [independent]
    assert not services.kernel.drawing_rasters


def test_unsaved_mixed_draft_delete_locked_constraint_is_atomic(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.core.sketch_layers import SketchLayer

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    line = LineEntity(uuid4().hex, (120, 0), (140, 0))
    assert canvas.replace_draft_entities((line,))
    constraint = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        layer_name="locked",
    )
    canvas.constraints = [constraint]
    assert canvas.document_layer_table is not None
    canvas.document_layer_table = canvas.document_layer_table.add(
        SketchLayer("locked", locked=True)
    )
    canvas.layer_table = canvas.document_layer_table
    canvas.selected_entity_ids = {line.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    count = loaded.document.command_count
    assert not canvas.delete_selected()
    assert loaded.document.command_count == count
    assert canvas.entities == [line] and canvas.constraints == [constraint]
    assert services.kernel.drawing_rasters == (original,)
    assert "锁定" in canvas.message


def test_erase_command_box_selects_image_and_constrained_draft(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    line = LineEntity(uuid4().hex, (120, 0), (140, 0))
    assert canvas.replace_draft_entities((line,))
    dimension = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(line.entity_id, "geometry"),), 20, "mm"
    )
    canvas.constraints = [dimension]
    canvas.selected_raster_ids.clear()
    canvas.selected_entity_ids.clear()
    assert getattr(editor, _ACTIVATE_COMMAND_TRANSFORM)("erase")
    for point in ((-10, 60), (150, -10)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert canvas.selected_entity_ids == {line.entity_id}
    assert canvas.selected_raster_ids == {original.image_id}
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    assert not canvas.entities and not canvas.constraints and not services.kernel.drawing_rasters
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert canvas.entities == [line] and canvas.constraints == [dimension]
    assert services.kernel.drawing_rasters == (original,)


def test_unsaved_picture_and_dimension_delete_undo_redo(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    line = LineEntity(uuid4().hex, (120, 0), (140, 0))
    assert canvas.replace_draft_entities((line,))
    dimension = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(line.entity_id, "geometry"),), 20, "mm"
    )
    canvas.constraints = [dimension]
    canvas.selected_entity_ids.clear()
    canvas.selected_raster_ids = {original.image_id}
    canvas.selected_constraint_ids = {dimension.constraint_id}
    assert canvas.delete_selected()
    assert canvas.entities == [line] and not canvas.constraints
    assert not services.kernel.drawing_rasters
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert canvas.entities == [line] and canvas.constraints == [dimension]
    assert services.kernel.drawing_rasters == (original,)
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert canvas.entities == [line] and not canvas.constraints
    assert not services.kernel.drawing_rasters


@pytest.mark.parametrize("unrelated_draft", (False, True))
def test_saved_dimension_and_picture_delete_undo_redo(
    qtbot: QtBot, tmp_path: Path, unrelated_draft: bool
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    line = LineEntity(uuid4().hex, (120, 0), (140, 0))
    dimension = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(line.entity_id, "geometry"),), 20, "mm"
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    draft = LineEntity(uuid4().hex, (160, 0), (180, 0))
    if unrelated_draft:
        assert canvas.replace_draft_entities((draft,))
    canvas.selected_entity_ids.clear()
    canvas.selected_raster_ids = {original.image_id}
    canvas.selected_constraint_ids = {dimension.constraint_id}
    assert canvas.delete_selected()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches[0].entities == (line,)
    assert not services.kernel.sketches[0].constraints and not services.kernel.drawing_rasters
    assert canvas.entities == ([draft] if unrelated_draft else [])
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches == (sketch,) and services.kernel.drawing_rasters == (original,)
    assert canvas.entities == ([draft] if unrelated_draft else [])
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert not services.kernel.sketches[0].constraints and not services.kernel.drawing_rasters
    assert canvas.entities == ([draft] if unrelated_draft else [])
    path = tmp_path / "saved-dimension-image-delete.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=[])
    app.open_app_document(reopened, path)
    assert not reopened.kernel.sketches[0].constraints and not reopened.kernel.drawing_rasters


def test_saved_dimension_image_and_locked_line_delete_is_atomic(qtbot: QtBot) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (120, 0), (140, 0))
    dimension = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(line.entity_id, "geometry"),), 20, "mm"
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    canvas.background_entities = tuple(
        (entity, replace(layer, locked=True)) for entity, layer in canvas.background_entities
    )
    canvas.selected_entity_ids = {line.entity_id}
    canvas.selected_constraint_ids = {dimension.constraint_id}
    canvas.selected_raster_ids = {original.image_id}
    count = loaded.document.command_count
    assert canvas.delete_selected()
    assert loaded.document.command_count == count
    assert services.kernel.sketches == (sketch,) and services.kernel.drawing_rasters == (original,)
    assert "锁定" in editor.status_label.text()


def test_saved_picture_geometry_dimension_delete_as_one_step(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    line = LineEntity(uuid4().hex, (120, 0), (140, 0))
    dimension = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(line.entity_id, "geometry"),), 20, "mm"
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    canvas.selected_entity_ids = {line.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    canvas.selected_constraint_ids = {dimension.constraint_id}
    assert canvas.delete_selected()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert not services.kernel.sketches[0].entities
    assert not services.kernel.sketches[0].constraints and not services.kernel.drawing_rasters
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches == (sketch,) and services.kernel.drawing_rasters == (original,)
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert not services.kernel.sketches[0].entities
    assert not services.kernel.sketches[0].constraints and not services.kernel.drawing_rasters


@pytest.mark.parametrize("numeric", (False, True))
def test_picture_saved_and_draft_move_as_one_step(qtbot: QtBot, numeric: bool) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    saved = LineEntity(uuid4().hex, (120, 0), (140, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    draft = LineEntity(uuid4().hex, (160, 0), (180, 0))
    assert canvas.replace_draft_entities((draft,))
    canvas.selected_entity_ids = {saved.entity_id, draft.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    if numeric:
        editor.delta_u_field.setValue(10)
        getattr(editor, _APPLY_TRANSFORM)("move")
    else:
        canvas.begin_transform("move")
        canvas.add_coordinate_point((0, 0), exact_point=True)
        canvas.add_coordinate_point((10, 0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert _line_start(canvas.entities[0]) == (170, 0)
    assert _line_start(services.kernel.sketches[0].entities[0]) == (130, 0)
    assert services.kernel.drawing_rasters[0].origin_mm == (10, 0)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert canvas.entities == [draft] and services.kernel.sketches == (sketch,)
    assert services.kernel.drawing_rasters == (original,)
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert _line_start(canvas.entities[0]) == (170, 0)
    assert _line_start(services.kernel.sketches[0].entities[0]) == (130, 0)
    assert services.kernel.drawing_rasters[0].origin_mm == (10, 0)


def test_picture_saved_and_draft_move_rolls_back_failed_draft(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    saved = LineEntity(uuid4().hex, (120, 0), (140, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    draft = LineEntity(uuid4().hex, (160, 0), (180, 0))
    assert canvas.replace_draft_entities((draft,))
    canvas.selected_entity_ids = {saved.entity_id, draft.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    count = loaded.document.command_count
    monkeypatch.setattr(canvas, "replace_draft_entities", _reject_draft_replacement)
    canvas.begin_transform("move")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((10, 0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert canvas.entities == [draft] and services.kernel.sketches == (sketch,)
    assert services.kernel.drawing_rasters == (original,)
    assert loaded.document.command_count == count
    assert "回滚" in editor.status_label.text()


def test_picture_saved_and_draft_move_rejects_duplicate_identity(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    saved = LineEntity(uuid4().hex, (120, 0), (140, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    draft = LineEntity(saved.entity_id, (160, 0), (180, 0))
    assert canvas.replace_draft_entities((draft,))
    canvas.selected_entity_ids = {saved.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    count = loaded.document.command_count
    getattr(window, _ON_DRAWING_MOVE)(
        editor, getattr(window, _SESSION_ID), (saved.entity_id,), (10.0, 0.0)
    )
    assert loaded.document.command_count == count
    assert canvas.entities == [draft] and services.kernel.sketches == (sketch,)
    assert services.kernel.drawing_rasters == (original,)
    assert "身份重复" in editor.status_label.text()


@pytest.mark.parametrize("operation", ("scale", "rotate", "numeric_rotate"))
def test_picture_saved_and_draft_affine_as_one_step(qtbot: QtBot, operation: str) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    saved = LineEntity(uuid4().hex, (120, 0), (140, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((10, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    draft = LineEntity(uuid4().hex, (160, 0), (180, 0))
    assert canvas.replace_draft_entities((draft,))
    canvas.selected_entity_ids = {saved.entity_id, draft.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    if operation == "numeric_rotate":
        editor.angle_field.setValue(90)
        getattr(editor, _APPLY_TRANSFORM)("rotate")
    else:
        canvas.begin_transform(operation)
        canvas.add_coordinate_point((0, 0), exact_point=True)
        assert (
            canvas.apply_scale_factor(2)
            if operation == "scale"
            else canvas.apply_rotation_angle(90)
        )
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    if operation == "scale":
        assert _line_start(canvas.entities[0]) == (320, 0)
        assert _line_start(services.kernel.sketches[0].entities[0]) == (240, 0)
        assert services.kernel.drawing_rasters[0].width_mm == 2 * original.width_mm
    else:
        assert _line_start(canvas.entities[0]) == pytest.approx((0, 160))
        assert _line_start(services.kernel.sketches[0].entities[0]) == pytest.approx((0, 120))
        assert services.kernel.drawing_rasters[0].origin_mm == pytest.approx((0, 10))
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert canvas.entities == [draft] and services.kernel.sketches == (sketch,)
    assert services.kernel.drawing_rasters == (original,)
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    if operation == "scale":
        assert _line_start(canvas.entities[0]) == (320, 0)
        assert _line_start(services.kernel.sketches[0].entities[0]) == (240, 0)
        assert services.kernel.drawing_rasters[0].width_mm == 2 * original.width_mm
    else:
        assert _line_start(canvas.entities[0]) == pytest.approx((0, 160))
        assert _line_start(services.kernel.sketches[0].entities[0]) == pytest.approx((0, 120))
        assert services.kernel.drawing_rasters[0].origin_mm == pytest.approx((0, 10))


@pytest.mark.parametrize("keep_source", (False, True))
def test_picture_saved_and_draft_mirror_as_one_step(qtbot: QtBot, keep_source: bool) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    saved = LineEntity(uuid4().hex, (120, 0), (140, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    draft = LineEntity(uuid4().hex, (160, 0), (180, 0))
    assert canvas.replace_draft_entities((draft,))
    canvas.selected_entity_ids = {saved.entity_id, draft.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    canvas.begin_transform("mirror", ask_mirror_erase=True)
    canvas.add_coordinate_point((10, 0), exact_point=True)
    canvas.add_coordinate_point((10, 20), exact_point=True)
    assert canvas.confirm_mirror_erase(not keep_source)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)

    def check_result() -> None:
        assert (
            len(canvas.entities)
            == len(services.kernel.sketches[0].entities)
            == 1 + int(keep_source)
        )
        assert len(services.kernel.drawing_rasters) == 1 + int(keep_source)
        assert _line_start(canvas.entities[-1]) == pytest.approx((-140, 0))
        assert _line_start(services.kernel.sketches[0].entities[-1]) == pytest.approx((-100, 0))
        assert next(
            item for item in services.kernel.drawing_rasters if item.mirrored
        ).origin_mm == pytest.approx((20, 0))

    check_result()
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert canvas.entities == [draft] and services.kernel.sketches == (sketch,)
    assert services.kernel.drawing_rasters == (original,)
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    check_result()


@pytest.mark.parametrize("mode", ("continuous", "array", "fit"))
def test_picture_saved_and_draft_copy_command(qtbot: QtBot, mode: str) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    saved = LineEntity(uuid4().hex, (120, 0), (140, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    draft = LineEntity(uuid4().hex, (160, 0), (180, 0))
    assert canvas.replace_draft_entities((draft,))
    canvas.selected_entity_ids = {saved.entity_id, draft.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    canvas.begin_transform("copy")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    if mode == "continuous":
        for point in ((10, 0), (20, 0)):
            canvas.add_coordinate_point(point, exact_point=True)
            qtbot.waitUntil(
                lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000
            )
    else:
        assert canvas.begin_copy_array()
        canvas.set_copy_array_count(3)
        if mode == "fit":
            canvas.set_copy_array_fit()
        canvas.add_coordinate_point((20 if mode == "fit" else 10, 0), exact_point=True)
        qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert len(canvas.entities) == len(services.kernel.sketches[0].entities) == 3
    assert len(services.kernel.drawing_rasters) == 3
    for expected in (2, 1) if mode == "continuous" else (1,):
        assert canvas.undo_copy_placement()
        qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
        assert len(canvas.entities) == len(services.kernel.sketches[0].entities) == expected
        assert len(services.kernel.drawing_rasters) == expected
    assert canvas.entities == [draft] and services.kernel.sketches == (sketch,)
    assert services.kernel.drawing_rasters == (original,)


def test_three_kind_copy_rejects_missing_draft_history(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    saved = LineEntity(uuid4().hex, (120, 0), (140, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    draft = LineEntity(uuid4().hex, (160, 0), (180, 0))
    assert canvas.replace_draft_entities((draft,))
    canvas.selected_entity_ids = {saved.entity_id, draft.entity_id}
    canvas.selected_raster_ids = {services.kernel.drawing_rasters[0].image_id}
    canvas.begin_transform("copy")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((10, 0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    count = loaded.document.command_count
    del editor.mixed_draft_history[count]
    assert canvas.undo_copy_placement()
    assert loaded.document.command_count == count
    assert len(canvas.entities) == len(services.kernel.sketches[0].entities) == 2
    assert len(services.kernel.drawing_rasters) == 2
    assert "不能撤销" in editor.status_label.text()


def test_three_kind_copy_rolls_back_and_ends_on_draft_failure(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    saved = LineEntity(uuid4().hex, (120, 0), (140, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    draft = LineEntity(uuid4().hex, (160, 0), (180, 0))
    assert canvas.replace_draft_entities((draft,))
    canvas.selected_entity_ids = {saved.entity_id, draft.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    count = loaded.document.command_count
    monkeypatch.setattr(canvas, "replace_draft_entities", _reject_draft_replacement)
    canvas.begin_transform("copy")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((10, 0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert canvas.active_transform is None
    assert canvas.entities == [draft] and services.kernel.sketches == (sketch,)
    assert services.kernel.drawing_rasters == (original,)
    assert loaded.document.command_count == count
    assert "回滚" in editor.status_label.text()


@pytest.mark.parametrize("select_dimensions", (False, True))
def test_picture_saved_and_draft_delete_as_one_step(qtbot: QtBot, select_dimensions: bool) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    saved = LineEntity(uuid4().hex, (120, 0), (140, 0))
    saved_dimension = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(saved.entity_id, "geometry"),), 20, "mm"
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved,), (saved_dimension,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    draft = LineEntity(uuid4().hex, (160, 0), (180, 0))
    assert canvas.replace_draft_entities((draft,))
    draft_dimension = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(draft.entity_id, "geometry"),), 20, "mm"
    )
    canvas.constraints = [draft_dimension]
    canvas.selected_entity_ids = {saved.entity_id, draft.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    if select_dimensions:
        canvas.selected_constraint_ids = {
            saved_dimension.constraint_id,
            draft_dimension.constraint_id,
        }
    assert canvas.delete_selected()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert not canvas.entities and not canvas.constraints
    assert not services.kernel.sketches[0].entities and not services.kernel.sketches[0].constraints
    assert not services.kernel.drawing_rasters
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert canvas.entities == [draft] and canvas.constraints == [draft_dimension]
    assert services.kernel.sketches == (sketch,) and services.kernel.drawing_rasters == (original,)
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert not canvas.entities and not canvas.constraints
    assert not services.kernel.sketches[0].entities and not services.kernel.sketches[0].constraints
    assert not services.kernel.drawing_rasters


def test_picture_saved_and_draft_delete_locked_dimension_is_atomic(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.core.sketch_layers import SketchLayer

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    saved = LineEntity(uuid4().hex, (120, 0), (140, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    draft = LineEntity(uuid4().hex, (160, 0), (180, 0))
    assert canvas.replace_draft_entities((draft,))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(draft.entity_id, "geometry"),),
        20,
        "mm",
        layer_name="locked",
    )
    assert canvas.document_layer_table is not None
    canvas.document_layer_table = canvas.document_layer_table.add(
        SketchLayer("locked", locked=True)
    )
    canvas.layer_table = canvas.document_layer_table
    canvas.constraints = [dimension]
    canvas.selected_entity_ids = {saved.entity_id, draft.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    count = loaded.document.command_count
    assert canvas.delete_selected()
    assert loaded.document.command_count == count
    assert canvas.entities == [draft] and canvas.constraints == [dimension]
    assert services.kernel.sketches == (sketch,) and services.kernel.drawing_rasters == (original,)
    assert "锁定" in editor.status_label.text()


def test_picture_saved_and_draft_delete_rolls_back_failed_draft(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    saved = LineEntity(uuid4().hex, (120, 0), (140, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    draft = LineEntity(uuid4().hex, (160, 0), (180, 0))
    assert canvas.replace_draft_entities((draft,))
    canvas.selected_entity_ids = {saved.entity_id, draft.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    count = loaded.document.command_count
    monkeypatch.setattr(canvas, "replace_draft_entities", _reject_draft_replacement)
    assert canvas.delete_selected()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert canvas.entities == [draft] and services.kernel.sketches == (sketch,)
    assert services.kernel.drawing_rasters == (original,)
    assert loaded.document.command_count == count
    assert "回滚" in editor.status_label.text()


def test_three_kind_delete_includes_unrelated_selected_dimensions(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    saved = LineEntity(uuid4().hex, (120, 0), (140, 0))
    other = LineEntity(uuid4().hex, (200, 0), (220, 0))
    saved_dimension = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(other.entity_id, "geometry"),), 20, "mm"
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (other,), (saved_dimension,))
    app.commit_new_sketch(services, loaded, first, session_identity=0)
    app.commit_new_sketch(services, loaded, second, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    draft = LineEntity(uuid4().hex, (160, 0), (180, 0))
    other_draft = LineEntity(uuid4().hex, (240, 0), (260, 0))
    assert canvas.replace_draft_entities((draft, other_draft))
    draft_dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(other_draft.entity_id, "geometry"),),
        20,
        "mm",
    )
    canvas.constraints = [draft_dimension]
    canvas.selected_entity_ids = {saved.entity_id, draft.entity_id}
    canvas.selected_constraint_ids = {saved_dimension.constraint_id, draft_dimension.constraint_id}
    canvas.selected_raster_ids = {original.image_id}
    assert canvas.delete_selected()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert canvas.entities == [other_draft] and not canvas.constraints
    assert not services.kernel.sketches[0].entities
    assert services.kernel.sketches[1].entities == (other,)
    assert not services.kernel.sketches[1].constraints and not services.kernel.drawing_rasters
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert canvas.entities == [draft, other_draft] and canvas.constraints == [draft_dimension]
    assert services.kernel.sketches == (first, second) and services.kernel.drawing_rasters == (
        original,
    )
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert canvas.entities == [other_draft] and not canvas.constraints
    assert services.kernel.sketches[1].entities == (other,)
    assert not services.kernel.sketches[1].constraints and not services.kernel.drawing_rasters


def test_three_kind_move_restores_partial_draft_exception(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, SketchEntity, WorkPlaneFrame

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    saved = LineEntity(uuid4().hex, (120, 0), (140, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    draft = LineEntity(uuid4().hex, (160, 0), (180, 0))
    extra = LineEntity(uuid4().hex, (200, 0), (220, 0))
    assert canvas.replace_draft_entities((draft,))
    assert canvas.replace_draft_entities((draft, extra))
    assert canvas.undo_last_operation() and canvas.can_redo
    canvas.selected_entity_ids = {saved.entity_id, draft.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    count = loaded.document.command_count
    position = canvas.history_position
    original_replace = canvas.replace_draft_entities

    def fail_after_mutation(
        entities: tuple[SketchEntity, ...],
        *,
        remove_dependent_constraints: bool = False,
        remove_constraint_ids: frozenset[str] = frozenset(),
    ) -> bool:
        assert original_replace(
            entities,
            remove_dependent_constraints=remove_dependent_constraints,
            remove_constraint_ids=remove_constraint_ids,
        )
        raise ValueError("injected draft failure")

    monkeypatch.setattr(canvas, "replace_draft_entities", fail_after_mutation)
    canvas.begin_transform("move")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((10, 0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert canvas.entities == [draft] and canvas.history_position == position and canvas.can_redo
    assert services.kernel.sketches == (sketch,) and services.kernel.drawing_rasters == (original,)
    assert loaded.document.command_count == count
    assert "回滚" in editor.status_label.text()


def test_picture_draft_move_restores_partial_draft_exception(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, SketchEntity

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    draft = LineEntity(uuid4().hex, (120, 0), (140, 0))
    extra = LineEntity(uuid4().hex, (160, 0), (180, 0))
    assert canvas.replace_draft_entities((draft,))
    assert canvas.replace_draft_entities((draft, extra))
    assert canvas.undo_last_operation() and canvas.can_redo
    canvas.selected_entity_ids = {draft.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    count, position = loaded.document.command_count, canvas.history_position
    original_replace = canvas.replace_draft_entities

    def fail_after_mutation(
        entities: tuple[SketchEntity, ...],
        *,
        remove_dependent_constraints: bool = False,
        remove_constraint_ids: frozenset[str] = frozenset(),
    ) -> bool:
        assert original_replace(
            entities,
            remove_dependent_constraints=remove_dependent_constraints,
            remove_constraint_ids=remove_constraint_ids,
        )
        raise ValueError("injected draft failure")

    monkeypatch.setattr(canvas, "replace_draft_entities", fail_after_mutation)
    canvas.begin_transform("move")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((10, 0), exact_point=True)
    assert canvas.active_transform is None
    assert canvas.entities == [draft] and canvas.history_position == position and canvas.can_redo
    assert services.kernel.drawing_rasters == (original,) and loaded.document.command_count == count
    assert "回滚" in canvas.message


@pytest.mark.parametrize("mode", ("draft", "saved", "both", "both_ref"))
def test_picture_and_geometry_scale_copy(qtbot: QtBot, mode: str) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    saved = LineEntity(uuid4().hex, (120, 0), (140, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved,))
    if mode != "draft":
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
        editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((10, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    draft = LineEntity(uuid4().hex, (160, 0), (180, 0))
    if mode != "saved":
        assert canvas.replace_draft_entities((draft,))
    canvas.selected_entity_ids = ({saved.entity_id} if mode != "draft" else set()) | (
        {draft.entity_id} if mode != "saved" else set()
    )
    canvas.selected_raster_ids = {original.image_id}
    canvas.begin_transform("scale")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    assert canvas.enable_scale_copy()
    if mode == "both_ref":
        assert canvas.start_scale_reference()
        assert canvas.apply_scale_length(10)
        assert canvas.apply_scale_length(20)
    else:
        assert canvas.apply_scale_factor(2)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert len(services.kernel.drawing_rasters) == 2
    copied = next(
        item for item in services.kernel.drawing_rasters if item.image_id != original.image_id
    )
    assert copied.origin_mm == (20, 0) and copied.width_mm == 2 * original.width_mm
    if mode != "draft":
        assert len(services.kernel.sketches[0].entities) == 2
        assert services.kernel.sketches[0].entities[0] == saved
        assert _line_start(services.kernel.sketches[0].entities[1]) == (240, 0)
    if mode != "saved":
        assert len(canvas.entities) == 2 and canvas.entities[0] == draft
        assert _line_start(canvas.entities[1]) == (320, 0)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.drawing_rasters == (original,)
    assert canvas.entities == ([draft] if mode != "saved" else [])
    if mode != "draft":
        assert services.kernel.sketches == (sketch,)
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert len(services.kernel.drawing_rasters) == 2
    if mode != "draft":
        assert len(services.kernel.sketches[0].entities) == 2
    if mode != "saved":
        assert len(canvas.entities) == 2


@pytest.mark.parametrize("mode", ("draft", "saved", "both", "both_ref"))
def test_picture_and_geometry_rotation_copy(qtbot: QtBot, mode: str) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    saved = LineEntity(uuid4().hex, (120, 0), (140, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved,))
    if mode != "draft":
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
        editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((10, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    draft = LineEntity(uuid4().hex, (160, 0), (180, 0))
    if mode != "saved":
        assert canvas.replace_draft_entities((draft,))
    canvas.selected_entity_ids = ({saved.entity_id} if mode != "draft" else set()) | (
        {draft.entity_id} if mode != "saved" else set()
    )
    canvas.selected_raster_ids = {original.image_id}
    canvas.begin_transform("rotate")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    if mode == "both_ref":
        assert canvas.start_rotation_reference()
        canvas.set_rotation_reference_angle(30)
    assert canvas.enable_rotation_copy()
    if mode == "both_ref":
        assert canvas.apply_rotation_target_angle(120)
    else:
        assert canvas.apply_rotation_angle(90)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert len(services.kernel.drawing_rasters) == 2
    copied = next(
        item for item in services.kernel.drawing_rasters if item.image_id != original.image_id
    )
    assert copied.origin_mm == pytest.approx((0, 10)) and copied.angle_deg == 90
    if mode != "draft":
        assert len(services.kernel.sketches[0].entities) == 2
        assert services.kernel.sketches[0].entities[0] == saved
        assert _line_start(services.kernel.sketches[0].entities[1]) == pytest.approx((0, 120))
    if mode != "saved":
        assert len(canvas.entities) == 2 and canvas.entities[0] == draft
        assert _line_start(canvas.entities[1]) == pytest.approx((0, 160))
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.drawing_rasters == (original,)
    assert canvas.entities == ([draft] if mode != "saved" else [])
    if mode != "draft":
        assert services.kernel.sketches == (sketch,)
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert len(services.kernel.drawing_rasters) == 2
    if mode != "draft":
        assert len(services.kernel.sketches[0].entities) == 2
    if mode != "saved":
        assert len(canvas.entities) == 2


@pytest.mark.parametrize("operation", ("copy", "scale", "rotate", "mirror"))
def test_picture_and_tangent_objects_copy_preserves_original_relation(
    qtbot: QtBot, operation: str
) -> None:
    from uuid import uuid4

    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.sketch import CircleEntity, LineEntity, Sketch, WorkPlaneFrame

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    circle = CircleEntity(uuid4().hex, (10, 5), 5)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((50, 20), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    canvas.selected_entity_ids = {line.entity_id, circle.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    canvas.begin_transform(operation, ask_mirror_erase=operation == "mirror")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    if operation == "copy":
        canvas.add_coordinate_point((30, 0), exact_point=True)
    elif operation == "scale":
        assert canvas.enable_scale_copy() and canvas.apply_scale_factor(2)
    elif operation == "rotate":
        assert canvas.enable_rotation_copy() and canvas.apply_rotation_angle(90)
    else:
        canvas.add_coordinate_point((20, 0), exact_point=True)
        assert canvas.confirm_mirror_erase(False)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert "副本未继承" in editor.status_label.text()
    if operation == "copy":
        canvas.cancel_transform()
    assert services.kernel.cross_sketch_tangencies == (relation,)
    assert all(len(sketch.entities) == 2 for sketch in services.kernel.sketches)
    assert len(services.kernel.drawing_rasters) == 2
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches == (first, second)
    assert services.kernel.cross_sketch_tangencies == (relation,)
    assert services.kernel.drawing_rasters == (original,)
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.cross_sketch_tangencies == (relation,)
    assert all(len(sketch.entities) == 2 for sketch in services.kernel.sketches)
    assert len(services.kernel.drawing_rasters) == 2


@pytest.mark.parametrize(
    ("mode", "operation"),
    (
        ("draft", "copy"),
        ("draft", "scale"),
        ("draft", "rotate"),
        ("draft", "mirror"),
        ("both", "copy"),
    ),
)
def test_picture_draft_copy_reports_omitted_constraints(
    qtbot: QtBot, mode: str, operation: str
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    saved = LineEntity(uuid4().hex, (120, 0), (140, 0))
    if mode == "both":
        app.commit_new_sketch(
            services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved,)), session_identity=0
        )
        editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((10, 0), exact_point=True)
    draft = LineEntity(uuid4().hex, (160, 0), (180, 0))
    assert canvas.replace_draft_entities((draft,))
    dimension = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(draft.entity_id, "geometry"),), 20, "mm"
    )
    canvas.constraints = [dimension]
    canvas.selected_entity_ids = {draft.entity_id} | (
        {saved.entity_id} if mode == "both" else set()
    )
    canvas.selected_raster_ids = {services.kernel.drawing_rasters[0].image_id}
    canvas.begin_transform(operation, ask_mirror_erase=operation == "mirror")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    if operation == "copy":
        canvas.add_coordinate_point((30, 0), exact_point=True)
    elif operation == "scale":
        assert canvas.enable_scale_copy() and canvas.apply_scale_factor(2)
    elif operation == "rotate":
        assert canvas.enable_rotation_copy() and canvas.apply_rotation_angle(90)
    else:
        canvas.add_coordinate_point((20, 0), exact_point=True)
        assert canvas.confirm_mirror_erase(False)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert len(canvas.entities) == 2 and canvas.constraints == [dimension]
    assert len(services.kernel.drawing_rasters) == 2
    assert "副本未继承" in editor.status_label.text()


@pytest.mark.parametrize(
    ("operation", "select_member"),
    (("copy", False), ("scale", True), ("rotate", False), ("mirror", True)),
)
def test_picture_and_array_object_copy_preserves_array(
    qtbot: QtBot, operation: str, select_member: bool
) -> None:
    from uuid import uuid4

    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    source_ref = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    target_ref = ArrayEntityRef(sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (source_ref,),
        (ArrayMember(source_ref, target_ref, 0, 1),),
    )
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((50, 20), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    canvas.selected_entity_ids = {(target if select_member else source).entity_id}
    canvas.selected_raster_ids = {original.image_id}
    canvas.begin_transform(operation, ask_mirror_erase=operation == "mirror")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    if operation == "copy":
        canvas.add_coordinate_point((30, 0), exact_point=True)
    elif operation == "scale":
        assert canvas.enable_scale_copy() and canvas.apply_scale_factor(2)
    elif operation == "rotate":
        assert canvas.enable_rotation_copy() and canvas.apply_rotation_angle(90)
    else:
        canvas.add_coordinate_point((20, 0), exact_point=True)
        assert canvas.confirm_mirror_erase(False)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert "未继承原对象的阵列关联" in editor.status_label.text()
    if operation == "copy":
        canvas.cancel_transform()
    assert services.kernel.associative_arrays == (array,)
    assert len(services.kernel.sketches[0].entities) == 3
    assert len(services.kernel.drawing_rasters) == 2
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches == (sketch,) and services.kernel.associative_arrays == (array,)
    assert services.kernel.drawing_rasters == (original,)
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.associative_arrays == (array,)
    assert len(services.kernel.sketches[0].entities) == 3
    assert len(services.kernel.drawing_rasters) == 2


def test_picture_and_pending_array_member_copy_keeps_array(qtbot: QtBot, tmp_path: Path) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((50, 20), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert canvas.replace_draft_entities((source,))
    canvas.selected_raster_ids.clear()
    canvas.selected_entity_ids = {source.entity_id}
    command = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "8", "AS", "Y", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(canvas.pending_associative_arrays) == 1
    array = canvas.pending_associative_arrays[0]
    member_id = array.members[0].target.entity_id
    original_entities = tuple(canvas.entities)
    canvas.selected_entity_ids = {member_id}
    canvas.selected_raster_ids = {original.image_id}
    canvas.begin_transform("copy")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((30, 0), exact_point=True)
    assert len(canvas.entities) == 3 and len(services.kernel.drawing_rasters) == 2
    assert canvas.pending_associative_arrays == [array]
    assert "阵列关联" in canvas.message and "未继承" in canvas.message
    canvas.cancel_transform()
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert tuple(canvas.entities) == original_entities and canvas.pending_associative_arrays == [
        array
    ]
    assert services.kernel.drawing_rasters == (original,)
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert len(canvas.entities) == 3 and canvas.pending_associative_arrays == [array]
    assert len(services.kernel.drawing_rasters) == 2
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    saved_array = services.kernel.associative_arrays[0]
    assert saved_array.array_id == array.array_id
    assert saved_array.sources[0].entity_id == source.entity_id
    assert saved_array.members[0].target.entity_id == member_id
    assert saved_array.sources[0].sketch_id == services.kernel.sketches[0].sketch_id
    assert saved_array.members[0].target.sketch_id == services.kernel.sketches[0].sketch_id
    path = tmp_path / "pending-array-picture-copy.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=[])
    app.open_app_document(reopened, path)
    assert reopened.kernel.associative_arrays == (saved_array,)
    assert len(reopened.kernel.sketches[0].entities) == 3
    assert len(reopened.kernel.drawing_rasters) == 2


@pytest.mark.parametrize("operation", ("scale", "rotate", "mirror"))
def test_picture_pending_array_affine_copy(qtbot: QtBot, operation: str) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((50, 20), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert canvas.replace_draft_entities((source,))
    canvas.selected_raster_ids.clear()
    canvas.selected_entity_ids = {source.entity_id}
    command = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "8", "AS", "Y", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    array = canvas.pending_associative_arrays[0]
    original_entities = tuple(canvas.entities)
    canvas.selected_entity_ids = {array.members[0].target.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    canvas.begin_transform(operation, ask_mirror_erase=operation == "mirror")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    if operation == "scale":
        assert canvas.enable_scale_copy() and canvas.apply_scale_factor(2)
    elif operation == "rotate":
        assert canvas.enable_rotation_copy() and canvas.apply_rotation_angle(90)
    else:
        canvas.add_coordinate_point((20, 0), exact_point=True)
        assert canvas.confirm_mirror_erase(False)
    assert len(canvas.entities) == 3 and len(services.kernel.drawing_rasters) == 2
    assert canvas.pending_associative_arrays == [array]
    assert "阵列关联" in canvas.message and "未继承" in canvas.message
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert tuple(canvas.entities) == original_entities and canvas.pending_associative_arrays == [
        array
    ]
    assert services.kernel.drawing_rasters == (original,)


def test_picture_and_pending_tangent_copy_preserves_relation(qtbot: QtBot, tmp_path: Path) -> None:
    from uuid import uuid4

    from mycad.core.sketch import CircleEntity, LineEntity, Sketch, WorkPlaneFrame

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((50, 20), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    circle = CircleEntity(uuid4().hex, (10, 5), 5)
    assert canvas.replace_draft_entities((circle,))
    canvas.pending_cross_tangencies = [(line.entity_id, circle.entity_id)]
    canvas.selected_entity_ids = {circle.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    canvas.begin_transform("copy")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((30, 0), exact_point=True)
    assert len(canvas.entities) == 2 and len(services.kernel.drawing_rasters) == 2
    assert canvas.pending_cross_tangencies == [(line.entity_id, circle.entity_id)]
    assert "约束关系" in canvas.message and "未继承" in canvas.message
    canvas.cancel_transform()
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert canvas.entities == [circle]
    assert canvas.pending_cross_tangencies == [(line.entity_id, circle.entity_id)]
    assert services.kernel.drawing_rasters == (original,)
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    path = tmp_path / "pending-tangent-picture-copy.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=[])
    app.open_app_document(reopened, path)
    assert len(reopened.kernel.cross_sketch_tangencies) == 1
    relation = reopened.kernel.cross_sketch_tangencies[0]
    assert {relation.first.entity_id, relation.second.entity_id} == {
        line.entity_id,
        circle.entity_id,
    }
    assert len(reopened.kernel.drawing_rasters) == 2


@pytest.mark.parametrize("operation", ("copy", "scale", "rotate", "mirror"))
def test_three_way_copy_preserves_pending_tangency(
    qtbot: QtBot, tmp_path: Path, operation: str
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import CircleEntity, LineEntity, Sketch, WorkPlaneFrame

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,)), session_identity=0
    )
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((50, 20), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    circle = CircleEntity(uuid4().hex, (10, 5), 5)
    assert canvas.replace_draft_entities((circle,))
    canvas.pending_cross_tangencies = [(line.entity_id, circle.entity_id)]
    canvas.selected_entity_ids = {line.entity_id, circle.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    canvas.begin_transform(operation, ask_mirror_erase=operation == "mirror")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    if operation == "copy":
        canvas.add_coordinate_point((30, 0), exact_point=True)
    elif operation == "scale":
        assert canvas.enable_scale_copy() and canvas.apply_scale_factor(2)
    elif operation == "rotate":
        assert canvas.enable_rotation_copy() and canvas.apply_rotation_angle(90)
    else:
        canvas.add_coordinate_point((20, 0), exact_point=True)
        assert canvas.confirm_mirror_erase(False)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert len(canvas.entities) == 2 and len(services.kernel.drawing_rasters) == 2
    assert sum(len(sketch.entities) for sketch in services.kernel.sketches) == 2
    assert canvas.pending_cross_tangencies == [(line.entity_id, circle.entity_id)]
    assert "约束关系" in editor.status_label.text() and "未继承" in editor.status_label.text()
    if operation == "copy":
        canvas.cancel_transform()
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert canvas.entities == [circle] and services.kernel.drawing_rasters == (original,)
    assert canvas.pending_cross_tangencies == [(line.entity_id, circle.entity_id)]
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    path = tmp_path / "three-way-pending-tangent-copy.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=[])
    app.open_app_document(reopened, path)
    assert len(reopened.kernel.cross_sketch_tangencies) == 1
    relation = reopened.kernel.cross_sketch_tangencies[0]
    assert {relation.first.entity_id, relation.second.entity_id} == {
        line.entity_id,
        circle.entity_id,
    }
    assert len(reopened.kernel.drawing_rasters) == 2


@pytest.mark.parametrize("valid_tangent", (True, False))
@pytest.mark.parametrize("operation", ("move", "scale", "rotate", "mirror"))
@pytest.mark.parametrize("selection", ("all", "partial"))
def test_three_way_move_preserves_pending_tangency(
    qtbot: QtBot, tmp_path: Path, valid_tangent: bool, operation: str, selection: str
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import CircleEntity, LineEntity, Sketch, WorkPlaneFrame

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    other = LineEntity(uuid4().hex, (0, 20), (20, 20))
    saved_entities = (line, other) if selection == "partial" else (line,)
    app.commit_new_sketch(
        services,
        loaded,
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), saved_entities),
        session_identity=0,
    )
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((50, 20), exact_point=True)
    original_image = services.kernel.drawing_rasters[0]
    circle = CircleEntity(uuid4().hex, (10, 5 if valid_tangent else 6), 5)
    assert canvas.replace_draft_entities((circle,))
    pair = (line.entity_id, circle.entity_id)
    canvas.pending_cross_tangencies = [pair]
    canvas.selected_entity_ids = (
        {other.entity_id, circle.entity_id} if selection == "partial" else set(pair)
    )
    canvas.selected_raster_ids = {original_image.image_id}
    canvas.begin_transform(operation, ask_mirror_erase=operation == "mirror")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    if operation == "move":
        canvas.add_coordinate_point((0, 3), exact_point=True)
    elif operation == "scale":
        assert canvas.apply_scale_factor(2)
    elif operation == "rotate":
        assert canvas.apply_rotation_angle(90)
    else:
        canvas.add_coordinate_point((0, 20), exact_point=True)
        assert canvas.confirm_mirror_erase(True)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    if selection == "partial":
        assert canvas.entities == [circle] and canvas.pending_cross_tangencies == [pair]
        assert services.kernel.sketches[0].entities == saved_entities
        assert services.kernel.drawing_rasters == (original_image,)
        assert "同时选择" in editor.status_label.text()
        return
    if not valid_tangent:
        assert canvas.entities == [circle] and canvas.pending_cross_tangencies == [pair]
        assert services.kernel.sketches[0].entities == (line,)
        assert services.kernel.drawing_rasters == (original_image,)
        assert "回滚" in editor.status_label.text()
        return
    assert canvas.pending_cross_tangencies == [pair]
    assert isinstance(canvas.entities[0], CircleEntity)
    expected_center = {"move": (10, 8), "scale": (20, 10), "rotate": (-5, 10), "mirror": (-10, 5)}
    assert canvas.entities[0].center_mm == pytest.approx(expected_center[operation])
    assert services.kernel.sketches[0].entities != (line,)
    assert services.kernel.drawing_rasters != (original_image,)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert canvas.entities == [circle] and canvas.pending_cross_tangencies == [pair]
    assert services.kernel.sketches[0].entities == (line,)
    assert services.kernel.drawing_rasters == (original_image,)
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert canvas.pending_cross_tangencies == [pair]
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    path = tmp_path / "three-way-tangent-move.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=[])
    app.open_app_document(reopened, path)
    assert len(reopened.kernel.cross_sketch_tangencies) == 1
    relation = reopened.kernel.cross_sketch_tangencies[0]
    assert {relation.first.entity_id, relation.second.entity_id} == set(pair)


@pytest.mark.parametrize("operation", ("copy", "scale", "rotate", "mirror"))
@pytest.mark.parametrize("source_kind", ("draft", "saved"))
def test_three_way_copy_preserves_pending_array(
    qtbot: QtBot, tmp_path: Path, operation: str, source_kind: str
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    saved_line = LineEntity(uuid4().hex, (0, 10), (2, 10))
    app.commit_new_sketch(
        services,
        loaded,
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved_line,)),
        session_identity=0,
    )
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((50, 20), exact_point=True)
    original_image = services.kernel.drawing_rasters[0]
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert canvas.replace_draft_entities((source,))
    canvas.selected_raster_ids.clear()
    array_source = source if source_kind == "draft" else saved_line
    canvas.selected_entity_ids = {array_source.entity_id}
    command = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "8", "AS", "Y", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    array = canvas.pending_associative_arrays[0]
    member_id = array.members[0].target.entity_id
    original_entities = tuple(canvas.entities)
    canvas.selected_entity_ids = {saved_line.entity_id, member_id}
    canvas.selected_raster_ids = {original_image.image_id}
    canvas.begin_transform(operation, ask_mirror_erase=operation == "mirror")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    if operation == "copy":
        canvas.add_coordinate_point((30, 0), exact_point=True)
    elif operation == "scale":
        assert canvas.enable_scale_copy() and canvas.apply_scale_factor(2)
    elif operation == "rotate":
        assert canvas.enable_rotation_copy() and canvas.apply_rotation_angle(90)
    else:
        canvas.add_coordinate_point((20, 0), exact_point=True)
        assert canvas.confirm_mirror_erase(False)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert len(canvas.entities) == 3 and len(services.kernel.drawing_rasters) == 2
    assert len(services.kernel.sketches[0].entities) == 2
    assert canvas.pending_associative_arrays == [array]
    assert "阵列关联" in editor.status_label.text() and "未继承" in editor.status_label.text()
    if operation == "copy":
        canvas.cancel_transform()
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert tuple(canvas.entities) == original_entities and canvas.pending_associative_arrays == [
        array
    ]
    assert services.kernel.drawing_rasters == (original_image,)
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    saved_array = services.kernel.associative_arrays[0]
    assert saved_array.array_id == array.array_id
    assert saved_array.sources[0].entity_id == array_source.entity_id
    assert saved_array.members[0].target.entity_id == member_id
    path = tmp_path / "three-way-pending-array-copy.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=[])
    app.open_app_document(reopened, path)
    assert reopened.kernel.associative_arrays == (saved_array,)
    assert len(reopened.kernel.drawing_rasters) == 2


def test_unsaved_mixed_draft_clipboard_cross_drawing(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    source = window.active_sketch_dialog()
    assert source is not None
    canvas = source.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    line = LineEntity(uuid4().hex, (120, 0), (140, 0))
    assert canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    canvas.selected_raster_ids = {original.image_id}
    assert canvas.copy_to_clipboard()
    window.act_new_drawing.trigger()
    target = window.active_sketch_dialog()
    assert target is not None and target is not source
    assert target.canvas.begin_clipboard_paste()
    target.canvas.add_coordinate_point((200, 50), exact_point=True)
    assert len(services.kernel.sketches) == 1 and len(services.kernel.drawing_rasters) == 1
    assert _line_start(services.kernel.sketches[0].entities[0]) == (200, 50)
    assert services.kernel.drawing_rasters[0].origin_mm == (80, 50)


def test_unsaved_mixed_draft_move_save_reopen(qtbot: QtBot, tmp_path: Path) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    image_id = services.kernel.drawing_rasters[0].image_id
    line = LineEntity(uuid4().hex, (120, 0), (140, 0))
    assert canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    canvas.selected_raster_ids = {image_id}
    canvas.begin_transform("move")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((10, 20), exact_point=True)
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    path = tmp_path / "draft-move.my2d"
    save_document(loaded.document, path)
    app.open_app_document(services, path)
    assert services.kernel.drawing_rasters[0].origin_mm == (10, 20)
    assert _line_start(services.kernel.sketches[0].entities[0]) == (130, 20)


def test_picture_batch_window_undo_redo(qtbot: QtBot) -> None:
    from dataclasses import replace

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    unit = window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    for point in ((0, 0), (120, 0)):
        assert canvas.begin_clipboard_paste()
        canvas.add_coordinate_point(point, exact_point=True)
    originals = services.kernel.drawing_rasters
    assert len(originals) == 2 and canvas.commit_raster_batch is not None
    moved = tuple(replace(item, origin_mm=(item.origin_mm[0], 50)) for item in originals)
    canvas.commit_raster_batch("update", moved)
    assert services.kernel.drawing_rasters == moved
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_rasters == originals, timeout=10000)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    window.request_redo()
    qtbot.waitUntil(lambda: services.kernel.drawing_rasters == moved, timeout=10000)


def test_picture_multi_window_delete_is_one_undo_step(qtbot: QtBot) -> None:
    from dataclasses import replace

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    for point in ((0, 0), (30, 0)):
        assert canvas.begin_clipboard_paste()
        canvas.add_coordinate_point(point, exact_point=True)
        image_ref = services.kernel.drawing_rasters[-1]
        assert canvas.commit_raster_edit is not None
        canvas.commit_raster_edit("update", replace(image_ref, width_mm=20, height_mm=10))
    originals = services.kernel.drawing_rasters
    canvas.selected_raster_id = None
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 5)))
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        pos=canvas.local_to_screen((35, 5)),
    )
    assert canvas.selected_raster_ids == {image.image_id for image in originals}
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
        pos=canvas.local_to_screen((5, 5)),
    )
    assert canvas.selected_raster_ids == {originals[1].image_id}
    for point in ((-5, 15), (55, -5)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert canvas.selected_raster_ids == {image.image_id for image in originals}
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    assert not services.kernel.drawing_rasters
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_rasters == originals, timeout=10000)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    window.request_redo()
    qtbot.waitUntil(lambda: not services.kernel.drawing_rasters, timeout=10000)


def test_picture_multi_transform_commits_once(qtbot: QtBot) -> None:
    from dataclasses import replace

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    for point in ((0, 0), (30, 0)):
        assert canvas.begin_clipboard_paste()
        canvas.add_coordinate_point(point, exact_point=True)
        assert canvas.commit_raster_edit is not None
        canvas.commit_raster_edit(
            "update", replace(services.kernel.drawing_rasters[-1], width_mm=20, height_mm=10)
        )
    originals = services.kernel.drawing_rasters
    for point in ((-5, 15), (55, -5)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    before = loaded.document.command_count
    canvas.begin_transform("scale")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    assert canvas.apply_scale_factor(2)
    scaled = services.kernel.drawing_rasters
    assert [item.width_mm for item in scaled] == [40, 40]
    assert scaled[1].origin_mm == (60, 0)
    assert loaded.document.command_count == before + 1
    assert canvas.selected_raster_ids == {item.image_id for item in originals}
    canvas.begin_transform("rotate")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    assert canvas.apply_rotation_angle(90)
    rotated = services.kernel.drawing_rasters
    assert [item.angle_deg for item in rotated] == [90, 90]
    assert rotated[1].origin_mm == pytest.approx((0, 60))
    canvas.begin_transform("mirror", keep_source=False)
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((10, 0), exact_point=True)
    mirrored = services.kernel.drawing_rasters
    assert all(item.mirrored and item.angle_deg == -90 for item in mirrored)
    unit = window.execution_unit
    assert unit is not None
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_rasters == rotated, timeout=10000)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    window.request_redo()
    qtbot.waitUntil(lambda: services.kernel.drawing_rasters == mirrored, timeout=10000)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    before_copy = loaded.document.command_count
    canvas.begin_transform("mirror", keep_source=True)
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((10, 0), exact_point=True)
    copied = services.kernel.drawing_rasters
    assert len(copied) == 4 and copied[:2] == mirrored
    assert all(not item.mirrored and item.angle_deg == 90 for item in copied[2:])
    assert loaded.document.command_count == before_copy + 1
    assert canvas.selected_raster_ids == {item.image_id for item in copied[2:]}


def test_multiple_pictures_clipboard_cross_drawing_and_undo(qtbot: QtBot) -> None:
    from dataclasses import replace

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    for point in ((0, 0), (30, 0)):
        assert canvas.begin_clipboard_paste()
        canvas.add_coordinate_point(point, exact_point=True)
        assert canvas.commit_raster_edit is not None
        canvas.commit_raster_edit(
            "update",
            replace(services.kernel.drawing_rasters[-1], width_mm=20, height_mm=10, angle_deg=30),
        )
    originals = services.kernel.drawing_rasters
    canvas.selected_raster_ids = {item.image_id for item in originals}
    assert canvas.copy_to_clipboard()
    window.act_new_drawing.trigger()
    target = window.active_sketch_dialog()
    assert target is not None and target is not editor
    window.menu_edit.aboutToShow.emit()
    assert window.act_paste.isEnabled()
    window.act_paste.trigger()
    assert target.canvas.clipboard_paste_active
    target.canvas.add_coordinate_point((10, 20), exact_point=True)
    pasted = services.kernel.drawing_rasters
    assert len(pasted) == 2
    assert [item.origin_mm for item in pasted] == [(10, 20), (40, 20)]
    assert all(item.angle_deg == 30 and item.width_mm == 20 for item in pasted)
    assert not ({item.image_id for item in pasted} & {item.image_id for item in originals})
    assert target.canvas.selected_raster_ids == {item.image_id for item in pasted}
    window.request_undo()
    qtbot.waitUntil(lambda: not services.kernel.drawing_rasters, timeout=10000)
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    window.request_redo()
    qtbot.waitUntil(lambda: services.kernel.drawing_rasters == pasted, timeout=10000)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert target.canvas.begin_clipboard_paste()
    QTest.keyClick(target.canvas, Qt.Key.Key_Escape)
    assert not target.canvas.clipboard_paste_active
    assert services.kernel.drawing_rasters == pasted


def test_bad_picture_group_clipboard_does_not_fall_back_to_external_image(qtbot: QtBot) -> None:
    from PySide6.QtCore import QByteArray, QMimeData

    from mycad.ui.drawing_clipboard import DRAWING_RASTER_GROUP_MIME

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    mime = QMimeData()
    mime.setImageData(image)
    mime.setData(DRAWING_RASTER_GROUP_MIME, QByteArray(b"{}"))
    QApplication.clipboard().setMimeData(mime)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    assert not editor.canvas.begin_clipboard_paste()
    assert not editor.canvas.clipboard_paste_active
    assert not services.kernel.drawing_rasters


def test_pasting_geometry_clears_previous_picture_selection(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    picture_id = services.kernel.drawing_rasters[0].image_id
    line = LineEntity(uuid4().hex, (120, 0), (140, 0))
    assert canvas.replace_draft_entities((line,))
    canvas.selected_raster_id = None
    canvas.selected_entity_ids = {line.entity_id}
    assert canvas.copy_to_clipboard()
    canvas.selected_entity_ids.clear()
    canvas.selected_raster_id = picture_id
    assert canvas.begin_clipboard_paste()
    assert not canvas.selected_raster_ids
    canvas.add_coordinate_point((160, 0), exact_point=True)
    assert len(canvas.entities) == 2 and not canvas.selected_raster_ids
    assert canvas.selected_entity_ids


def test_starting_drawing_tool_clears_picture_selection(qtbot: QtBot) -> None:
    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    assert canvas.begin_clipboard_paste()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    assert canvas.selected_raster_ids
    assert canvas.set_tool("直线")
    assert not canvas.selected_raster_ids
    canvas.add_coordinate_point((120, 0), exact_point=True)
    canvas.add_coordinate_point((140, 0), exact_point=True)
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    assert len(services.kernel.drawing_rasters) == 1
