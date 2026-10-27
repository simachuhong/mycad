# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Capture real X11/OpenGL P2-28 viewport frames and record GL context."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from OpenGL.GL import GL_RENDERER, GL_VENDOR, GL_VERSION, glGetString
from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from mycad.app import build_app, new_document
from mycad.ui.main_window import MainWindow

OUTPUT = Path(__file__).resolve().parent
BACKGROUND = (239, 243, 247, 255)
FLANGE_COMMANDS: tuple[tuple[str, dict[str, object]], ...] = (
    ("feature.cylinder", {"radius": 40.0, "height": 8.0, "mode": "new"}),
    (
        "feature.hole",
        {
            "target_face": {"surface": "plane", "axis": "+Z", "rank": 0},
            "position": {"kind": "center"},
            "diameter": 20.0,
            "depth": {"kind": "through_all"},
        },
    ),
    (
        "feature.hole_pattern",
        {
            "base_hole": {
                "target_face": {"surface": "plane", "axis": "+Z", "rank": 0},
                "position": {"kind": "center"},
                "diameter": 6.0,
                "depth": {"kind": "through_all"},
            },
            "pattern": {
                "kind": "polar",
                "radius": 25.0,
                "count": 4,
                "start_angle_deg": 0,
            },
        },
    ),
)
CASES: dict[str, tuple[tuple[str, dict[str, object]], ...]] = {
    "empty": (),
    "flange": FLANGE_COMMANDS,
    "thin-plate": (("feature.box", {"size_x": 120.0, "size_y": 80.0, "size_z": 2.0}),),
    "cylinder": (("feature.cylinder", {"radius": 20.0, "height": 40.0}),),
}


def main() -> None:
    app = QApplication([])
    settings = tempfile.TemporaryDirectory(prefix="mycad-p2-28-shader-")
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, settings.name)
    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, settings.name)
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    services = build_app(discoverers=[])
    window = MainWindow(services=services)
    window.resize(1366, 768)
    view = window.viewport
    assert view is not None
    window.show()
    QTest.qWait(500)
    assert view.isValid(), "No real OpenGL context on this desktop"
    view.makeCurrent()
    context = {
        "vendor": glGetString(GL_VENDOR).decode(),
        "renderer": glGetString(GL_RENDERER).decode(),
        "version": glGetString(GL_VERSION).decode(),
        "qt_platform": app.platformName(),
    }
    view.doneCurrent()

    report: dict[str, object] = {
        "context": context,
        "settings_isolated": False,
        "screens": [],
        "limitations": [
            "Camera-ray selection is currently broken and remains in P2-31; the existing amber overlay was not visually distinct in this pass.",
            "Viewport framing and triangle mesh edges remain for P2-29/P2-30.",
        ],
    }
    screens: list[dict[str, object]] = []
    for name, commands in CASES.items():
        loaded = new_document(services)
        window.bind_document(loaded)
        for command_id, params in commands:
            loaded.bus.execute(command_id, params, "p2-28-render-check")
        view.refresh()
        view.fit_view()
        QTest.qWait(300)
        frame = view.grabFramebuffer()
        assert not frame.isNull(), name
        background = frame.pixelColor(8, 8).getRgb()
        assert background == BACKGROUND, (name, background)
        path = OUTPUT / f"{name}.png"
        assert frame.save(str(path))
        screen: dict[str, object] = {
            "case": name,
            "size": [frame.width(), frame.height()],
            "background_rgba": background,
            "center_rgba": frame.pixelColor(frame.width() // 2, frame.height() // 2).getRgb(),
            "screenshot": path.name,
        }
        if name == "flange":
            screen["top_face_sample"] = {
                "pixel_xy": [240, 160],
                "rgba": frame.pixelColor(240, 160).getRgb(),
                "surface": "flat top annulus away from holes, visually checked against screenshot",
            }
        screens.append(screen)
        loaded.document.mark_clean()

    settings_path = QSettings("MyCAD", "MyCAD").fileName()
    report["settings_isolated"] = Path(settings_path).is_relative_to(settings.name)
    assert report["settings_isolated"]
    report["screens"] = screens
    window.close()
    app.processEvents()
    settings.cleanup()
    report_path = OUTPUT / "render-check.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
