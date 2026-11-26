# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Two executables sharing a single dependency directory."""

import importlib.metadata
import os
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_submodules,
    copy_metadata,
)

build_root = Path(os.environ['MYCAD_BUILD_ROOT'])
root = Path(SPECPATH).resolve().parents[1]
datas = collect_data_files('mycad')
# build123d registers bundled fonts during import; ezdxf also reads package data.
datas += collect_data_files('build123d')
datas += collect_data_files('ezdxf')
binaries = []
hidden = collect_submodules('mycad')
for package in ('OCP', 'planegcs', 'cadquery_ocp_proxy'):
    package_data, package_binaries, package_hidden = collect_all(package)
    datas += package_data
    binaries += package_binaries
    hidden += package_hidden

# Preserve metadata for plugin discovery and dependencies that query versions.
for distribution in importlib.metadata.distributions():
    name = distribution.metadata['Name']
    datas += copy_metadata(name)
    # Native wheels may keep DLLs beside, rather than inside, their Python package.
    for item in distribution.files or ():
        if item.suffix.lower() in ('.dll', '.pyd'):
            path = Path(distribution.locate_file(item))
            if path.is_file() and '..' not in item.parts:
                binaries.append((str(path), str(item.parent)))
        elif any(part.endswith('.libs') for part in item.parts) and '..' not in item.parts:
            path = Path(str(distribution.locate_file(item)))
            if path.is_file():
                datas.append((str(path), str(item.parent)))

datas.append((str(build_root / 'payload'), 'release'))
options = dict(
    exclude_binaries=True,
    strip=False,
    upx=False,
    version=str(build_root / 'version-resource.txt'),
)
if os.environ.get('MYCAD_BUILD_ICON'):
    options['icon'] = os.environ['MYCAD_BUILD_ICON']

a = Analysis(
    [str(root / 'scripts/windows/launcher.py')],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=['pytest', '_pytest', 'tkinter', 'PySide6.QtWebEngineCore',
              'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick', 'PySide6.QtQml',
              'PySide6.QtQuick', 'PySide6.QtQuickWidgets'],
    hookspath=[],
    runtime_hooks=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
gui = EXE(pyz, a.scripts, [], name='MyCAD', console=False, **options)
cli = EXE(pyz, a.scripts, [], name='MyCAD-cli', console=True, **options)
coll = COLLECT(gui, cli, a.binaries, a.datas, strip=False, upx=False, name='MyCAD')
