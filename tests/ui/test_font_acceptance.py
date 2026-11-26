# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Font resource acceptance using real TTF, OTF and TTC samples."""

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtWidgets import QApplication

from mycad.core.drawing_text import DrawingText, TextStyle
from mycad.ui.font_manager import FontManager
from mycad.ui.font_resources import FontResourcesDialog
from mycad.ui.text_layout import layout_text

_SAMPLES = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/opentype/urw-base35/NimbusSans-Regular.otf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
)


@pytest.mark.parametrize("source", _SAMPLES, ids=["ttf", "otf", "ttc"])
def test_real_font_import_duplicate_and_restart(
    qapp: QApplication, tmp_path: Path, source: Path
) -> None:
    if not source.is_file():
        pytest.skip(f"Required fixed font sample is unavailable: {source}")
    source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    directory = tmp_path / "fonts"
    manager = FontManager(directory)
    families = manager.import_font(source)
    assert families
    duplicate = tmp_path / f"duplicate{source.suffix}"
    duplicate.write_bytes(source.read_bytes())
    assert manager.import_font(duplicate) == families
    assert len(list(directory.iterdir())) == 1
    assert set(families) <= set(FontManager(directory).load_imported())
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_digest


def test_failed_copy_or_registration_preserves_existing_resource_and_can_recover(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, other = _SAMPLES[:2]
    if not source.is_file() or not other.is_file():
        pytest.skip("Required fixed font samples are unavailable")
    manager = FontManager(tmp_path / "fonts")
    manager.import_font(source)
    before = {item.name: item.read_bytes() for item in manager.directory.iterdir()}
    with pytest.raises(FileNotFoundError):
        manager.import_font(tmp_path / "missing.ttf")
    with monkeypatch.context() as scoped:

        def fail_copy(src: object, dst: object) -> None:
            raise OSError("simulated copy failure")

        scoped.setattr("mycad.ui.font_manager.shutil.copyfile", fail_copy)
        with pytest.raises(OSError, match="copy failure"):
            manager.import_font(other)
    assert {item.name: item.read_bytes() for item in manager.directory.iterdir()} == before
    with monkeypatch.context() as scoped:

        def fail_register(path: Path) -> tuple[str, ...]:
            raise ValueError("simulated Qt registration failure")

        scoped.setattr(manager, "_register", fail_register)
        with pytest.raises(ValueError, match="registration failure"):
            manager.import_font(other)
    assert {item.name: item.read_bytes() for item in manager.directory.iterdir()} == before
    assert manager.import_font(other)
    assert len(list(manager.directory.iterdir())) == 2


def test_real_font_import_survives_cancelling_resource_dialog(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _SAMPLES[0]
    if not source.is_file():
        pytest.skip(f"Required fixed font sample is unavailable: {source}")
    manager = FontManager(tmp_path / "fonts")
    dialog = FontResourcesDialog(manager=manager)

    def choose(*_args: object) -> tuple[str, str]:
        return str(source), ""

    monkeypatch.setattr(
        "mycad.ui.font_resources.QFileDialog.getOpenFileName",
        choose,
    )
    dialog.import_button.click()
    assert "已导入" in dialog.status.text()
    selected = dialog.font_family.currentText()
    assert selected
    dialog.reject()
    reopened = FontManager(manager.directory)
    assert selected in reopened.load_imported()
    assert len(list(manager.directory.iterdir())) == 1


def test_unwritable_font_destination_reports_error_without_staging(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _SAMPLES[0]
    if not source.is_file():
        pytest.skip(f"Required fixed font sample is unavailable: {source}")
    manager = FontManager(tmp_path / "fonts")
    real_mkdir = Path.mkdir

    def deny_directory(
        path: Path, mode: int = 0o777, parents: bool = False, exist_ok: bool = False
    ) -> None:
        if path == manager.directory:
            raise PermissionError("font directory is not writable")
        real_mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

    monkeypatch.setattr(Path, "mkdir", deny_directory)
    with pytest.raises(PermissionError, match="not writable"):
        manager.import_font(source)
    assert not manager.directory.exists()


@pytest.mark.parametrize(
    "index,content", [(1, "ABC 123"), (2, "中文 ABC\n第二行")], ids=["otf", "cjk-ttc"]
)
def test_imported_font_can_shape_text_without_missing_glyphs(
    qapp: QApplication, tmp_path: Path, index: int, content: str
) -> None:
    source = _SAMPLES[index]
    if not source.is_file():
        pytest.skip(f"Required fixed font sample is unavailable: {source}")
    manager = FontManager(tmp_path / "fonts")
    families = manager.import_font(source)
    assert families
    style = TextStyle(font_family=families[0], height_mm=4)
    item = DrawingText(uuid4().hex, content, (0, 0), kind="mtext", align="top_left")
    layout = layout_text(item, style, manager)
    assert not layout.missing_glyphs
    assert layout.bounds.width() > 0 and layout.bounds.height() >= 4
