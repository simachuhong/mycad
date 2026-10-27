# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Output preview remains read-only until the user accepts export."""

from pytestqt.qtbot import QtBot

from mycad.formats.dxf_preview import DxfOutputPreview
from mycad.formats.providers.dxf_provider import DxfExchangeReport
from mycad.ui.dxf_output_preview import DxfOutputPreviewDialog


def test_output_preview_renders_zoom_fits_and_requires_explicit_acceptance(qtbot: QtBot) -> None:
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path d="M10 10 L90 90" stroke="black"/></svg>'
    preview = DxfOutputPreview(
        b"unwritten", svg, DxfExchangeReport("导出", "AC1024", "mm", 1, ("仅二维草图",))
    )
    dialog = DxfOutputPreviewDialog(preview, "example.dxf")
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    assert dialog.renderer.isValid()
    assert "仅二维草图" in dialog.report_label.text()
    original = dialog.view.transform().m11()
    dialog.zoom_in_button.click()
    assert dialog.view.transform().m11() > original
    dialog.fit_button.click()
    assert abs(dialog.view.transform().m11() - original) < 1e-6
    assert dialog.result() == dialog.DialogCode.Rejected
    dialog.export_button.click()
    assert dialog.result() == dialog.DialogCode.Accepted
