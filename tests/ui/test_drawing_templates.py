# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Visible template selection writes replayable sheet commands and shared outputs."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtPdf import QPdfDocument
from pytestqt.qtbot import QtBot

from mycad.app import build_app, new_document
from mycad.core.drawing import DrawingSheet
from mycad.core.drawing_codec import drawing_object_mapping
from mycad.core.drawing_templates import TemplateText, builtin_template
from mycad.formats.drawing_export import export_drawing_dxf
from mycad.ui.drawing_pdf import export_drawing_pdf
from mycad.ui.main_window import MainWindow
from tests.formats.test_drawing_export import tags
from tests.helpers.drawing_scene import drawing_scene


def test_builtin_selection_fields_and_undo(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    services = build_app(discoverers=[])
    loaded = new_document(services)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    bench = window.drawing_workbench
    unit = window.execution_unit
    assert unit is not None
    panel = bench.templates
    assert panel.selector.currentData() == "GB"
    panel.fields["图号"].setText("GB-001")
    bench.title.setText("轴承座")
    bench.create_sheet()
    qtbot.waitUntil(lambda: len(services.kernel.drawing_state.sheets) == 1 and not unit.is_busy)
    sheet = services.kernel.drawing_state.sheets[0]
    assert sheet.template is not None and sheet.template.standard.startswith("GB")
    assert dict(sheet.title)["图号"] == "GB-001"
    panel.selector.setCurrentIndex(panel.selector.findData("ISO"))
    bench.apply_sheet_settings()
    qtbot.waitUntil(lambda: not unit.is_busy)
    sheet = services.kernel.drawing_state.sheets[0]
    assert sheet.template is not None and sheet.template.standard.startswith("ISO")
    assert dict(sheet.title)["图号"] == "GB-001"
    bench.title.setText("修改标题")
    bench.title.editingFinished.emit()
    qtbot.waitUntil(lambda: not unit.is_busy)
    assert dict(services.kernel.drawing_state.sheets[0].title)["图号"] == "GB-001"
    loaded.bus.undo()
    bench.refresh()
    assert bench.title.text() == "轴承座"
    loaded.bus.undo()
    bench.refresh()
    assert panel.selector.currentData() == "GB"


def test_embedded_custom_size_survives_settings(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    services = build_app(discoverers=[])
    loaded = new_document(services)
    template = replace(
        builtin_template("GB", "A4"), template_id=str(uuid4()), name="企业模板", size_mm=(330, 240)
    )
    sheet = DrawingSheet(
        uuid4(), size_mm=template.size_mm, template=template, title=(("图号", "CUSTOM"),)
    )
    loaded.bus.execute("drawing.sheet.create", drawing_object_mapping(sheet))
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    bench = window.drawing_workbench
    unit = window.execution_unit
    assert unit is not None
    assert not bench.paper.isEnabled()
    bench.apply_sheet_settings()
    qtbot.waitUntil(lambda: not unit.is_busy)
    assert services.kernel.drawing_state.sheets[0].size_mm == (330, 240)
    assert services.kernel.drawing_state.sheets[0].template == template


@pytest.mark.parametrize("standard", ["GB", "ISO"])
def test_template_pdf_dxf_and_rotated_text(qtbot: QtBot, tmp_path: Path, standard: str) -> None:
    template = builtin_template(standard, "A4")
    template = replace(
        template,
        texts=(*template.texts, TemplateText((40, 50), "ROTATED", rotation_deg=90, align="center")),
    )
    scene = replace(
        drawing_scene(), template=template, title=(("标题", "法兰零件"), ("图号", "GB-009"))
    )
    pdf, dxf = tmp_path / "template.pdf", tmp_path / "template.dxf"
    export_drawing_pdf(scene, pdf)
    export_drawing_dxf(scene, dxf)
    doc = QPdfDocument()
    assert doc.load(str(pdf)) == QPdfDocument.Error.None_
    assert "GB-009" in doc.getAllText(0).text()
    assert "法兰零件" in doc.getAllText(0).text()
    data = tags(dxf)
    assert (1, "GB-009") in data
    assert (50, "90.0") in data
    assert (71, "2") in data


def test_import_preview_mapping_and_cancel_leave_document_untouched(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from PySide6.QtWidgets import QDialogButtonBox

    from mycad.ui.drawing_templates import TemplateImportDialog
    from tests.helpers.template_dxf import new_dxf

    path = tmp_path / "company.dxf"
    document = new_dxf()
    document.modelspace().add_line((10, 10), (280, 10))
    document.modelspace().add_text("COMPANY-001", dxfattribs={"insert": (50, 30), "height": 3})
    document.saveas(path)
    dialog = TemplateImportDialog(path)
    qtbot.addWidget(dialog)
    assert dialog.template is None
    dialog.preview()
    assert dialog.template is not None
    field_item = dialog.mapping.item(0, 1)
    assert field_item is not None
    field_item.setText("图号")
    assert dialog.template.texts[0].field == "图号"
    dialog.paper_width.setValue(300)
    assert dialog.template is None
    assert not dialog.buttons.button(QDialogButtonBox.StandardButton.Save).isEnabled()
    dialog.preview()
    assert dialog.template is not None and dialog.template.size_mm[0] == 300
    dialog.reject()
    assert not list(tmp_path.glob("*.json"))


def test_edit_title_keeps_unapplied_template_fields(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    bench = window.drawing_workbench
    unit = window.execution_unit
    assert unit is not None
    bench.create_sheet()
    qtbot.waitUntil(lambda: not unit.is_busy)
    bench.templates.fields["图号"].setText("PENDING-10")
    bench.title.setText("New title")
    bench.title.editingFinished.emit()
    qtbot.waitUntil(lambda: not unit.is_busy)
    assert bench.templates.fields["图号"].text() == "PENDING-10"
    bench.apply_sheet_settings()
    qtbot.waitUntil(lambda: not unit.is_busy)
    assert dict(services.kernel.drawing_state.sheets[0].title)["图号"] == "PENDING-10"


@pytest.mark.parametrize("align", ["center", "right"])
def test_multiline_template_alignment_matches_pdf(qtbot: QtBot, align: str) -> None:
    from PySide6.QtCore import QPointF
    from PySide6.QtWidgets import QGraphicsScene

    from mycad.core.drawing_paper import PaperText
    from mycad.ui.drawing_render import add_paper_text

    graphics = QGraphicsScene()
    item = add_paper_text(graphics, PaperText((100, 100), "WIDEST LINE\nI", align=align))
    block = item.document().begin()
    while block.isValid():
        layout = block.layout()
        assert layout is not None
        line = layout.lineAt(0)
        # Qt aligns glyphs within the line; line.x() remains the layout origin.
        rect = line.naturalTextRect()
        x = rect.center().x() if align == "center" else rect.right()
        assert item.mapToScene(QPointF(x, 0)).x() == pytest.approx(100, abs=0.05)
        block = block.next()


def test_import_entry_saves_library_without_applying_to_document(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QDialog, QFileDialog

    from mycad.ui.drawing_templates import DrawingTemplatePanel, TemplateImportDialog
    from tests.helpers.template_dxf import new_dxf

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    source = tmp_path / "template.dxf"
    document = new_dxf()
    document.modelspace().add_line((10, 10), (280, 10))
    document.saveas(source)
    services = build_app(discoverers=[])
    loaded = new_document(services)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    panel = window.drawing_workbench.templates

    def filename(*_args: object, **_kwargs: object) -> tuple[str, str]:
        return str(source), "DXF"

    def accept_preview(dialog: TemplateImportDialog) -> int:
        dialog.preview()
        assert dialog.template is not None
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QFileDialog, "getOpenFileName", filename)
    monkeypatch.setattr(TemplateImportDialog, "exec", accept_preview)
    panel.import_button.click()
    selected = str(panel.selector.currentData())
    assert selected in panel.imported
    assert not loaded.document.commands
    source.unlink()
    second = DrawingTemplatePanel()
    qtbot.addWidget(second)
    assert selected in second.imported
