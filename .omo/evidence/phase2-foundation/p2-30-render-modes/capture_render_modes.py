# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Capture engineering and diagnostic render modes for representative solids."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from mycad.app import build_app, new_document
from mycad.ui.main_window import MainWindow

OUTPUT = Path(__file__).resolve().parent
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
            "pattern": {"kind": "polar", "radius": 25.0, "count": 4, "start_angle_deg": 0},
        },
    ),
)
CASES: dict[str, tuple[tuple[str, dict[str, object]], ...]] = {
    "flat": (("feature.box", {"size_x": 50, "size_y": 40, "size_z": 8}),),
    "curved": (("feature.cylinder", {"radius": 25, "height": 45}),),
    "holed": FLANGE_COMMANDS,
    "filleted": (
        ("feature.box", {"size_x": 50, "size_y": 40, "size_z": 12}),
        (
            "modify.fillet",
            {
                "edges": [{"parent_faces": [{"surface": "plane", "axis": "+Z"}]}],
                "radius": 3,
            },
        ),
    ),
    "thin": (("feature.box", {"size_x": 120, "size_y": 60, "size_z": 1}),),
}
MODES = ("shaded", "shaded-edges", "engineering-wireframe", "mesh-diagnostic")


def main() -> None:
    app = QApplication([])
    settings = tempfile.TemporaryDirectory(prefix="mycad-p2-30-render-")
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, settings.name)
    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, settings.name)
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    services = build_app(discoverers=[])
    window = MainWindow(services=services)
    view = window.viewport
    assert view is not None
    window.showFullScreen()
    QTest.qWait(350)

    captures: list[dict[str, object]] = []
    for case_name, commands in CASES.items():
        loaded = new_document(services)
        window.bind_document(loaded)
        for command_id, params in commands:
            loaded.bus.execute(command_id, params, "p2-30-screen-check")
        view.refresh()
        view.fit_view()
        QTest.qWait(250)
        snapshot = view.snapshots()[-1]
        for mode in MODES:
            window.render_mode_actions[mode].trigger()
            QTest.qWait(100)
            path = OUTPUT / case_name / f"{mode}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            frame = window.grab()
            assert not frame.isNull()
            assert frame.save(str(path))
            captures.append(
                {
                    "case": case_name,
                    "mode": mode,
                    "logical_window_size": [window.width(), window.height()],
                    "image_size": [frame.width(), frame.height()],
                    "device_pixel_ratio": frame.devicePixelRatio(),
                    "boundary_edge_count": len(snapshot.boundary_edges),
                    "mesh_triangle_count": len(snapshot.mesh.triangle_indices),
                    "scene_item_count": len(view.items),
                    "screenshot": path.relative_to(OUTPUT).as_posix(),
                }
            )

    report = {
        "qt_platform": app.platformName(),
        "qt_scale_factor": app.primaryScreen().devicePixelRatio(),
        "cases": list(CASES),
        "modes": list(MODES),
        "captures": captures,
    }
    (OUTPUT / "render-check.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if window.loaded_document() is not None:
        window.loaded_document().document.mark_clean()
    window.close()
    app.processEvents()
    settings.cleanup()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
