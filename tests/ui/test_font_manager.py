# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Application font resources remain reproducible without installing system fonts."""

from pathlib import Path

import pytest
from ezdxf.fonts.font_manager import FONT_DIRECTORIES
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from mycad.core.drawing_text import TextStyle
from mycad.ui.font_manager import FontManager


def test_import_is_persistent_deduplicated_and_reloadable(
    qapp: QApplication, tmp_path: Path
) -> None:
    roots = [Path(path).expanduser() for values in FONT_DIRECTORIES.values() for path in values]
    source = next((p for root in roots if root.is_dir() for p in root.rglob("*.ttf")), None)
    if source is None:
        pytest.skip("No installed TrueType font available as an import fixture")
    manager = FontManager(tmp_path / "fonts")
    families = manager.import_font(source)
    assert families
    assert set(families) <= set(manager.families())
    copied = tmp_path / "renamed.ttf"
    copied.write_bytes(source.read_bytes())
    assert manager.import_font(copied) == families
    assert len(tuple((tmp_path / "fonts").iterdir())) == 1
    reopened = FontManager(tmp_path / "fonts")
    assert set(families) <= set(reopened.load_imported())
    style = TextStyle(font_family=families[0])
    assert reopened.font_file(style)
    assert reopened.substitution(style) == ""


def test_invalid_font_does_not_leave_staged_file(qapp: QApplication, tmp_path: Path) -> None:
    manager = FontManager(tmp_path / "fonts")
    broken = tmp_path / "broken.ttf"
    broken.write_bytes(b"not a font")
    with pytest.raises(ValueError, match="font|字体"):
        manager.import_font(broken)
    unsupported = tmp_path / "shape.shx"
    unsupported.write_bytes(b"shape")
    with pytest.raises(ValueError, match="TTF|OTF|TTC"):
        manager.import_font(unsupported)
    assert not tuple(manager.directory.iterdir())


def test_missing_request_preserves_style_and_reports_substitution(
    qapp: QApplication, tmp_path: Path
) -> None:
    manager = FontManager(tmp_path)
    style = TextStyle(font_family="MyCAD Missing Font 7192", font_file="missing.ttf")
    resolved = manager.resolve(style)
    assert resolved.pixelSize() == 100
    assert resolved.family() in QFontDatabase.families()
    assert manager.substitution(style)
    assert style.font_family == "MyCAD Missing Font 7192"
    assert manager.font_file(style) == "missing.ttf"
    assert manager.missing_glyphs("AA\U0010ffff\U0010ffff\n", style) == "\U0010ffff"
