# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Capture P2-29 Qt workbench states at physical target sizes and DPI factors."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

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
TARGET_PIXEL_SIZES = {"1920x1080": (1920, 1080), "1366x768": (1366, 768)}
CAPTURE_STATES = ("empty", "current-3d", "selected-feature", "plan-confirmation", "error-recovery")
TARGET_RESOLUTION = os.environ.get("MYCAD_CAPTURE_RESOLUTION")


def main() -> None:
    scale = float(os.environ.get("QT_SCALE_FACTOR", "1"))
    app = QApplication([])
    settings = tempfile.TemporaryDirectory(prefix="mycad-p2-29-workbench-")
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, settings.name)
    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, settings.name)
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    services = build_app(discoverers=[])
    window = MainWindow(services=services)
    view = window.viewport
    assert view is not None
    screen = app.primaryScreen()
    target_size = TARGET_PIXEL_SIZES.get(TARGET_RESOLUTION or "")
    target_logical_size = (
        (round(target_size[0] / scale), round(target_size[1] / scale))
        if target_size is not None
        else None
    )
    target_is_fullscreen = (
        screen is not None
        and target_size is not None
        and target_size
        == (
            round(screen.geometry().width() * screen.devicePixelRatio()),
            round(screen.geometry().height() * screen.devicePixelRatio()),
        )
    )
    if target_logical_size is not None:
        window.resize(*target_logical_size)
    if target_is_fullscreen:
        window.showFullScreen()
    else:
        window.show()
    QTest.qWait(350)

    screens: list[dict[str, object]] = []
    resolutions = {
        resolution: physical_size
        for resolution, physical_size in TARGET_PIXEL_SIZES.items()
        if TARGET_RESOLUTION is None or resolution == TARGET_RESOLUTION
    }
    assert resolutions, f"unsupported capture target: {TARGET_RESOLUTION!r}"
    for resolution, physical_size in resolutions.items():
        logical_size = (round(physical_size[0] / scale), round(physical_size[1] / scale))
        is_primary_fullscreen = target_is_fullscreen
        if TARGET_RESOLUTION is None:
            if is_primary_fullscreen:
                window.showFullScreen()
            else:
                window.showNormal()
                window.setWindowState(Qt.WindowState.WindowNoState)
                window.resize(*logical_size)
        QTest.qWait(250)
        assert window.width() <= logical_size[0] + 2, (
            resolution,
            scale,
            window.size().width(),
            logical_size[0],
            is_primary_fullscreen,
        )
        directory = OUTPUT / f"scale-{scale:g}" / resolution
        directory.mkdir(parents=True, exist_ok=True)

        for state in CAPTURE_STATES:
            if state == "empty":
                empty = new_document(services)
                window.bind_document(empty)
            elif state in ("current-3d", "selected-feature", "error-recovery"):
                loaded = new_document(services)
                window.bind_document(loaded)
                for command_id, params in FLANGE_COMMANDS:
                    loaded.bus.execute(command_id, params, "p2-29-screen-check")
                view.refresh()
                view.fit_view()
                QTest.qWait(200)
            if state == "selected-feature":
                window.right_panel.select_feature_ordinal(2)
            elif state == "plan-confirmation":
                window._on_palette_command("feature.box")
                window.act_view_plans.trigger()
            elif state == "error-recovery":
                window._show_error("示例错误：参数尺寸无效。当前模型和输入已保留，可修正后重试。")
                QTest.qWait(120)

            QTest.qWait(100)
            frame = window.grab()
            assert not frame.isNull(), (scale, resolution, state)
            path = directory / f"{state}.png"
            assert frame.save(str(path))
            logical_area = max(window.width() * window.height(), 1)
            viewport_area = view.width() * view.height()
            toolbar_actions = window.main_toolbar.actions()
            overflowed_actions = [
                action.text()
                for action in toolbar_actions
                if (button := window.main_toolbar.widgetForAction(action)) is not None
                and not button.isVisible()
            ]
            screens.append(
                {
                    "scale_factor": scale,
                    "physical_target": resolution,
                    "fullscreen": is_primary_fullscreen,
                    "logical_window_size": [window.width(), window.height()],
                    "captured_image_size": [frame.width(), frame.height()],
                    "device_pixel_ratio": frame.devicePixelRatio(),
                    "state": state,
                    "viewport_logical_size": [view.width(), view.height()],
                    "viewport_share_of_window": round(viewport_area / logical_area, 4),
                    "rendered_scene_item_count": len(view.items),
                    "current_solid_count": services.kernel.mass_properties().solid_count,
                    "bottom_panel_visible": not window.bottom_dock.isHidden(),
                    "left_panel_visible": not window.left_dock.isHidden(),
                    "toolbar_overflow_actions": overflowed_actions,
                    "screenshot": path.relative_to(OUTPUT).as_posix(),
                }
            )
            if state == "error-recovery":
                dialog = window.findChild(QMessageBox, "errorMessage")
                assert dialog is not None
                dialog_path = directory / "error-dialog.png"
                assert dialog.grab().save(str(dialog_path))
                screens[-1]["error_dialog_screenshot"] = dialog_path.relative_to(OUTPUT).as_posix()
                dialog.close()
            if state == "plan-confirmation":
                window.bottom_dock.hide()
                window.act_toggle_bottom_dock.setChecked(False)
                window.plan_draft = None

        window.resize(*logical_size)
        window.act_reset_layout.trigger()

    settings_path = QSettings("MyCAD", "MyCAD").fileName()
    report = {
        "qt_platform": app.platformName(),
        "qt_scale_factor": scale,
        "qsettings_isolated": Path(settings_path).is_relative_to(settings.name),
        "captures": screens,
        "not_implemented": [
            "The 2D drawing and sketch workspaces are not captured as product screens; their functional drawing tasks are P2-32+.",
            "The selected-feature screen demonstrates the existing right-panel feature/property state; viewport entity picking remains P2-31.",
        ],
    }
    assert report["qsettings_isolated"]
    (OUTPUT / f"render-check-scale-{scale:g}-{TARGET_RESOLUTION or 'all'}.json").write_text(
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
