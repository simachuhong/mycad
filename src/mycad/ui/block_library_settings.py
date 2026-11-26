# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Persistent configuration of local and read-only shared block roots."""

from pathlib import Path
from typing import cast
from uuid import NAMESPACE_URL, uuid5

from PySide6.QtCore import QSettings

from mycad.libraries.block_store import LibraryRoot

_SHARED_KEY = "drawing2d/blockLibrarySharedDirectories"


def _paths(settings: QSettings) -> tuple[Path, ...]:
    raw = settings.value(_SHARED_KEY, [], type=list)
    if not isinstance(raw, list):
        return ()
    return tuple(
        Path(item).absolute() for item in cast("list[object]", raw) if isinstance(item, str)
    )


def library_roots(settings: QSettings, local_directory: Path) -> tuple[LibraryRoot, ...]:
    """Rebuild roots from settings; unavailable shared paths remain visible."""
    roots = [LibraryRoot("local", local_directory.absolute(), False)]
    seen = {str(roots[0].path)}
    for path in _paths(settings):
        if str(path) in seen:
            continue
        seen.add(str(path))
        roots.append(
            LibraryRoot(uuid5(NAMESPACE_URL, f"mycad:block-library:{path}").hex, path, True)
        )
    return tuple(roots)


def add_shared_directory(settings: QSettings, path: Path) -> None:
    path = path.absolute()
    if not path.is_dir():
        raise ValueError("共享块库目录不可用。")
    values = list(_paths(settings))
    if path not in values:
        values.append(path)
    settings.setValue(_SHARED_KEY, [str(item) for item in values])


def remove_shared_directory(settings: QSettings, path: Path) -> None:
    path = path.absolute()
    settings.setValue(_SHARED_KEY, [str(item) for item in _paths(settings) if item != path])
