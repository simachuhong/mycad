# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Exercise navigation and topology selection in a live X11 workbench."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from mycad.app import build_app, new_document
from mycad.ui.main_window import MainWindow

OUTPUT = Path(__file__).resolve().parent


def main() -> None:
    app = QApplication([])
    settings = tempfile.TemporaryDirectory(prefix="mycad-p2-31-selection-")
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, settings.name)
    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, settings.name)
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute(
        "feature.box",
        {"size_x": 80.0, "size_y": 50.0, "size_z": 8.0, "mode": "new"},
        "p2-31-screen-check",
    )
    window = MainWindow(services=services)
    window.bind_document(loaded)
    view = window.viewport
    assert view is not None
    window.showFullScreen()
    QTest.qWait(400)

    window.orientation_actions["top"].trigger()
    window.projection_actions["orthographic"].trigger()
    window.act_show_coordinate_axes.trigger()
    window.act_show_xy_grid.trigger()
    view.fit_view()
    QTest.qWait(150)

    captures: list[dict[str, object]] = []

    def capture(state: str) -> None:
        view.repaint()
        app.processEvents()
        QTest.qWait(180)
        view.repaint()
        app.processEvents()
        screen = window.screen()
        assert screen is not None
        frame = screen.grabWindow(window.winId())
        assert not frame.isNull()
        path = OUTPUT / f"{state}.png"
        assert frame.save(str(path))
        viewport_frame = view.grabFramebuffer()
        assert not viewport_frame.isNull()
        viewport_path = OUTPUT / f"viewport-{state}.png"
        assert viewport_frame.save(str(viewport_path))
        viewport_origin = view.mapTo(window, view.rect().topLeft())
        viewport_center = view.rect().center()
        screen_center = viewport_origin + viewport_center
        desktop_center_rgb = frame.toImage().pixelColor(screen_center).getRgb()
        viewport_center_rgb = viewport_frame.pixelColor(viewport_center).getRgb()
        captures.append(
            {
                "state": state,
                "orientation_action": next(
                    name
                    for name, action in window.orientation_actions.items()
                    if action.isChecked()
                ),
                "projection": view.projection_mode(),
                "selection_filter": view.selection_filter(),
                "selection": None
                if view.selection() is None
                else {
                    "kind": view.selection().kind,
                    "body_ids": [str(identity) for identity in view.selection().body_ids],
                    "topology_ids": [str(identity) for identity in view.selection().topology_ids],
                    "geometry_revision": view.selection().geometry_revision,
                },
                "preselection": None
                if view.preselection() is None
                else {
                    "kind": view.preselection().kind,
                    "topology_ids": [
                        str(identity) for identity in view.preselection().topology_ids
                    ],
                },
                "coordinate_axes_visible": view.coordinate_axes_visible(),
                "xy_grid_visible": view.xy_grid_visible(),
                "document_revision": loaded.document.revision,
                "command_count": len(loaded.document.commands),
                "viewport_size": [view.width(), view.height()],
                "image_size": [frame.width(), frame.height()],
                "device_pixel_ratio": frame.devicePixelRatio(),
                "screenshot": path.name,
                "viewport_screenshot": viewport_path.name,
                "desktop_center_rgb": list(desktop_center_rgb),
                "viewport_center_rgb": list(viewport_center_rgb),
                "desktop_viewport_center_matches_framebuffer": (
                    desktop_center_rgb == viewport_center_rgb
                ),
            }
        )

    capture("standard-top-orthographic-axes-grid")
    window.projection_actions["perspective"].trigger()
    capture("standard-top-perspective-axes-grid")
    window.projection_actions["orthographic"].trigger()
    window.selection_filter_actions["face"].trigger()
    view.fit_view()

    center = view.rect().center()
    pointer_target = view.selection_target_at(center.x(), center.y(), "face")
    QCursor.setPos(view.mapToGlobal(view.rect().topLeft()))
    QTest.qWait(30)
    QCursor.setPos(view.mapToGlobal(center))
    QTest.qWait(120)
    preselection = view.preselection()
    assert preselection is not None and preselection.kind == "face", (
        view.selection_filter(),
        view.size().width(),
        view.size().height(),
        center.x(),
        center.y(),
        pointer_target,
    )
    capture("face-hover-preselection")

    before_revision = loaded.document.revision
    before_commands = loaded.document.commands
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=center)
    selection = view.selection()
    assert selection is not None and selection.kind == "face"
    assert loaded.document.revision == before_revision
    assert loaded.document.commands == before_commands
    viewport_frame = view.grabFramebuffer()
    assert not viewport_frame.isNull()
    assert viewport_frame.save(str(OUTPUT / "face-click-viewport.png"))
    viewport_center_rgb = viewport_frame.pixelColor(center).getRgb()
    capture("face-click-selection")

    window.orientation_actions["isometric"].trigger()
    capture("isometric-face-selection")
    assert window.right_panel is not None
    report = {
        "qt_platform": app.platformName(),
        "screen_geometry": None
        if app.primaryScreen() is None
        else [
            app.primaryScreen().geometry().width(),
            app.primaryScreen().geometry().height(),
        ],
        "document_revision_unchanged_by_selection": loaded.document.revision == before_revision,
        "command_history_unchanged_by_selection": loaded.document.commands == before_commands,
        "right_panel_selection_text": window.right_panel.view_selection_label.text(),
        "viewport_screenshot": "face-click-viewport.png",
        "viewport_center_rgb": list(viewport_center_rgb),
        "captures": captures,
    }
    assert report["document_revision_unchanged_by_selection"]
    assert report["command_history_unchanged_by_selection"]
    (OUTPUT / "render-check.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    loaded.document.mark_clean()
    window.close()
    app.processEvents()
    settings.cleanup()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
