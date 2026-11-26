# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Qt font resources local to MyCAD; requested document styles stay unchanged."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from ezdxf.fonts import fonts
from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import QFont, QFontDatabase, QFontInfo, QTextLayout

from mycad.core.drawing_text import TextStyle

_SUPPORTED = frozenset({".ttf", ".otf", ".ttc"})


class FontManager:
    """Manage persistent imported files and Qt application font registrations."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = (
            directory
            or Path(
                QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
            )
            / "MyCAD"
            / "fonts"
        )
        self._loaded: dict[Path, tuple[str, ...]] = {}
        self._family_files: dict[str, Path] = {}
        self.load_imported()

    def families(self) -> tuple[str, ...]:
        return tuple(QFontDatabase.families())

    def _register(self, path: Path) -> tuple[str, ...]:
        path = path.resolve()
        if path in self._loaded:
            return self._loaded[path]
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            raise ValueError("无法加载字体文件 (invalid font)")
        families = tuple(QFontDatabase.applicationFontFamilies(font_id))
        if not families:
            QFontDatabase.removeApplicationFont(font_id)
            raise ValueError("字体文件未提供可用字体 (invalid font)")
        self._loaded[path] = families
        for family in families:
            self._family_files.setdefault(family.casefold(), path)
        return families

    def import_font(self, path: Path) -> tuple[str, ...]:
        """Copy before registration; reject broken fonts without orphan resources."""
        path = Path(path)
        if path.suffix.lower() not in _SUPPORTED:
            raise ValueError("仅支持 TTF、OTF 和 TTC 字体")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.directory.mkdir(parents=True, exist_ok=True)
        for existing in self.directory.iterdir():
            if existing.name.startswith(digest + "-") and existing.suffix.lower() in _SUPPORTED:
                return self._register(existing)
        destination = self.directory / f"{digest}-{path.name}"
        staged: Path | None = None
        try:
            handle, name = tempfile.mkstemp(dir=self.directory, suffix=path.suffix.lower())
            os.close(handle)
            staged = Path(name)
            shutil.copyfile(path, staged)
            staged.replace(destination)
            staged = None
            return self._register(destination)
        except (OSError, ValueError):
            destination.unlink(missing_ok=True)
            raise
        finally:
            if staged is not None:
                staged.unlink(missing_ok=True)

    def load_imported(self) -> tuple[str, ...]:
        """Load all valid user resources; a broken local file cannot block startup."""
        families: list[str] = []
        if self.directory.is_dir():
            for path in sorted(self.directory.iterdir()):
                if path.is_file() and path.suffix.lower() in _SUPPORTED:
                    try:
                        families.extend(self._register(path))
                    except (OSError, ValueError):
                        continue
        return tuple(dict.fromkeys(families))

    def _requested_family(self, style: TextStyle) -> str:
        if style.font_family:
            return style.font_family
        if style.font_file:
            name = Path(style.font_file).name.casefold()
            for path, families in self._loaded.items():
                if path.name.casefold() == name or path.name[65:].casefold() == name:
                    return families[0]
            face = fonts.find_font_face(style.font_file)
            if face.filename.casefold() == name:
                return face.family
            return style.font_file
        return ""

    def resolve(self, style: TextStyle) -> QFont:
        """Use native shaping and fallback while retaining the original style record."""
        available = {family.casefold(): family for family in self.families()}
        requested = self._requested_family(style)
        family = available.get(requested.casefold(), "")
        if not family:
            family = next(
                (
                    available[name.casefold()]
                    for name in ("Noto Sans CJK SC", "Microsoft YaHei", "DejaVu Sans")
                    if name.casefold() in available
                ),
                QFontInfo(QFont()).family(),
            )
        font = QFontDatabase.font(family, style.font_style, 12)
        font.setPixelSize(100)
        font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        return font

    def substitution(self, style: TextStyle) -> str:
        """Return the actual replacement family, or empty for an available request."""
        requested = self._requested_family(style)
        if requested and requested.casefold() not in {name.casefold() for name in self.families()}:
            return QFontInfo(self.resolve(style)).family()
        return ""

    def font_file(self, style: TextStyle) -> str:
        """Return the portable requested identifier, never a silent fallback file."""
        if style.font_file:
            return Path(style.font_file).name
        family = self._requested_family(style) or QFontInfo(self.resolve(style)).family()
        imported = self._family_files.get(family.casefold())
        if imported is not None:
            return imported.name[65:]
        face = fonts.find_best_match(family=family, style=style.font_style)
        return (
            face.filename
            if face is not None and face.family.casefold() == family.casefold()
            else ""
        )

    def missing_glyphs(self, text: str, style: TextStyle) -> str:
        """Check native shaping, including Qt fallback runs, and deduplicate missing chars."""
        font = self.resolve(style)
        missing: list[str] = []
        for character in dict.fromkeys(text):
            if character.isspace():
                continue
            layout = QTextLayout(character, font)
            layout.beginLayout()
            line = layout.createLine()
            if line.isValid():
                line.setLineWidth(1e9)
            layout.endLayout()
            runs = layout.glyphRuns()
            if not runs or any(0 in run.glyphIndexes() for run in runs):
                missing.append(character)
        return "".join(missing)
