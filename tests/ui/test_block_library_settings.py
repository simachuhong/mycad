# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Shared block roots are persistent read-only settings, never deleted on removal."""

from pathlib import Path

from PySide6.QtCore import QSettings

from mycad.ui.block_library_settings import (
    add_shared_directory,
    library_roots,
    remove_shared_directory,
)


def test_shared_directory_settings_roundtrip_and_removal(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    local = tmp_path / "local"
    shared = tmp_path / "team"
    shared.mkdir()
    (shared / "keep.txt").write_text("keep", encoding="utf-8")
    add_shared_directory(settings, shared)
    add_shared_directory(settings, shared)
    roots = library_roots(settings, local)
    assert len(roots) == 2 and roots[0].path == local and not roots[0].read_only
    assert roots[1].path == shared and roots[1].read_only
    identity = roots[1].root_id
    assert library_roots(settings, local)[1].root_id == identity
    remove_shared_directory(settings, shared)
    assert len(library_roots(settings, local)) == 1
    assert (shared / "keep.txt").read_text(encoding="utf-8") == "keep"
