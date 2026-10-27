# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Real X11/GL inspection at an explicitly recorded physical size and Qt DPR."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from time import monotonic

from OpenGL.GL import GL_RENDERER, GL_VERSION, glGetString

from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QPushButton, QScrollArea

from mycad.app import build_app, new_document
from mycad.ui import main_window

OUTPUT = Path(__file__).resolve().parent


def main() -> None:
    app = QApplication([])
    with tempfile.TemporaryDirectory(prefix="mycad-f-closure-") as settings:
        main_window.QSettings = lambda *_: QSettings(
            str(Path(settings) / "ui.ini"), QSettings.Format.IniFormat
        )
        services = build_app(discoverers=[])
        loaded = new_document(services)
        loaded.bus.execute("feature.box", {"size_x": 80, "size_y": 50, "size_z": 8}, "inspection")
        window = main_window.MainWindow(services=services)
        window.bind_document(loaded)
        window._ask_save_dialog = lambda: "discard"
        scale = float(os.environ["QT_SCALE_FACTOR"])
        width, height = (int(value) for value in os.environ["MYCAD_CAPTURE_SIZE"].split("x"))
        folder = OUTPUT / f"{width}x{height}-{scale:g}"
        folder.mkdir(exist_ok=True)
        window.resize(round(width / scale), round(height / scale))
        window.show()
        QTest.qWait(150)
        view = window.viewport
        bar = window.modeling_command_bar
        assert view is not None and bar is not None
        before = loaded.document.commands
        report: dict[str, object] = {
            "platform": app.platformName(),
            "scale": scale,
            "dpr": view.devicePixelRatioF(),
            "physical_target": [width, height],
            "logical_window": [window.width(), window.height()],
        }
        assert abs(view.devicePixelRatioF() - scale) < 0.01
        assert window.width() <= round(width / scale) and window.height() <= round(height / scale)
        view.makeCurrent()
        report["gl_renderer"] = glGetString(GL_RENDERER).decode()
        report["gl_version"] = glGetString(GL_VERSION).decode()
        view.doneCurrent()
        report["display"] = os.environ.get("DISPLAY")
        captures = []

        def capture(name: str) -> None:
            QTest.qWait(100)
            view.repaint()
            QTest.qWait(60)
            framebuffer = view.grabFramebuffer()
            assert not framebuffer.isNull()
            assert framebuffer.save(str(folder / f"{name}-viewport.png"))
            frame = window.grab()
            assert frame.save(str(folder / f"{name}.png"))
            point = view.mapTo(window, view.rect().center())
            actual = frame.toImage().pixelColor(round(point.x() * scale), round(point.y() * scale))
            expected = framebuffer.pixelColor(
                round(view.rect().center().x() * scale), round(view.rect().center().y() * scale)
            )
            assert actual == expected, (name, actual.name(), expected.name())
            captures.append(
                {
                    "state": name,
                    "image_size": [frame.width(), frame.height()],
                    "center_matches_framebuffer": True,
                }
            )

        def wait_preview() -> QPushButton:
            button = bar.findChild(QPushButton, "modelingCommitButton")
            assert button is not None
            deadline = monotonic() + 30
            while not button.isEnabled() and monotonic() < deadline:
                QTest.qWait(20)
            assert button.isEnabled(), window.status_command.text()
            return button

        view.set_orientation("top")
        view.fit_view()
        edge = view.snapshots()[-1].boundary_edges[0]
        midpoint = tuple((a + b) / 2 for a, b in zip(edge.points[0], edge.points[1], strict=True))
        distance = view.camera_distance()
        tolerance_checks = []
        for zoom in (0.5, 1, 2):
            view.setCameraPosition(distance=distance * zoom)
            projected = view.project_world_point(midpoint)
            assert projected is not None
            inside = view.selection_target_at(projected[0], projected[1] + 5.9, "edge") is not None
            outside = view.selection_target_at(projected[0], projected[1] + 6.1, "edge") is None
            assert inside and outside
            tolerance_checks.append({"zoom": zoom, "5.9px_hit": inside, "6.1px_miss": outside})
        report["pick_tolerance"] = tolerance_checks
        view.set_orientation("isometric")
        view.fit_view()
        report["idle_viewport_share"] = (
            view.width() * view.height() / (window.width() * window.height())
        )
        capture("idle")

        layout_checks = []
        for command in (
            "feature.box",
            "feature.cylinder",
            "feature.extrude",
            "feature.revolve",
            "feature.hole",
            "feature.hole_pattern",
            "modify.boolean_cut",
            "modify.fillet",
        ):
            assert window.command_palette is not None
            window.command_palette.command_activated.emit(command)
            QTest.qWait(50)
            command_bar = window.fillet_command_bar if command == "modify.fillet" else bar
            assert command_bar is not None
            names = (
                ("filletCommitButton", "filletCancelButton")
                if command == "modify.fillet"
                else ("modelingCommitButton", "modelingCancelButton")
            )
            for name in names:
                button = command_bar.findChild(QPushButton, name)
                assert button is not None and button.isVisible()
                assert window.rect().contains(button.mapTo(window, QPoint()))
                assert window.rect().contains(button.mapTo(window, button.rect().bottomRight()))
                assert not button.visibleRegion().isEmpty()
            assert (
                command_bar.mapToGlobal(QPoint(0, command_bar.height())).y()
                <= view.mapToGlobal(QPoint()).y()
            )
            fields = command_bar.findChildren(QDoubleSpinBox)
            if fields:
                window.raise_()
                window.activateWindow()
                QTest.qWait(60)
                field = next(field for field in reversed(fields) if field.isVisible())
                field.setFocus(Qt.FocusReason.TabFocusReason)
                QTest.qWait(30)
                assert field.visibleRegion().boundingRect().width() >= field.width() - 2, (
                    command,
                    field.objectName(),
                    field.hasFocus(),
                    app.focusWidget(),
                    window.isActiveWindow(),
                )
            scroll = command_bar.findChild(QScrollArea, "commandFieldsScroll")
            assert scroll is not None
            layout_checks.append(
                {
                    "command": command,
                    "confirmation_visible": True,
                    "last_field_focus_visible": True,
                    "scroll_range": scroll.horizontalScrollBar().maximum(),
                }
            )
            if command == "feature.hole_pattern":
                capture("pattern-parameters")
            window._cancel_active_modeling_tool()
        report["commands"] = layout_checks

        window.command_palette.command_activated.emit("feature.extrude")
        view.set_orientation("isometric")
        view.fit_view()
        point = view.project_world_point((0, 0, 4))
        assert point is not None and view.pick_at(*point)
        button = wait_preview()
        assert loaded.document.commands == before
        capture("extrude-preview")
        # Numeric acceptance does not submit. Navigation keeps the source model selectable.
        field = bar.findChild(QDoubleSpinBox, "distance")
        assert field is not None
        field.setFocus()
        field.selectAll()
        QTest.keyClicks(field, "3")
        QTest.keyClick(field, Qt.Key.Key_Return)
        wait_preview()
        view.orbit(25, 10)
        point = view.project_world_point((10, 0, 4))
        assert point is not None and view.pick_at(*point)
        wait_preview()
        assert loaded.document.commands == before
        report["preview"] = {
            "numeric_enter_no_commit": True,
            "reselect_after_orbit": True,
            "source_revision": loaded.document.revision,
            "command_count": len(before),
        }
        window._cancel_active_modeling_tool()
        assert loaded.document.commands == before
        window._apply_theme_setting("dark", persist=False)
        capture("dark-current-model")
        report["cancel_unchanged"] = True
        report["captures"] = captures
        (folder / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        window.close()
        app.processEvents()
        print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
