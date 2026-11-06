# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""The sphere command uses a dedicated, renderable primitive glyph."""

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon

from mycad.ui.cad_icons import cad_icon, command_icon_name


def test_sphere_command_uses_its_own_icon_in_both_themes(qapp: object) -> None:
    name = command_icon_name("feature.sphere")
    assert name == "sphere"
    for theme in ("light", "dark"):
        icon = cad_icon(name, theme)
        assert not icon.pixmap(QSize(24, 24), QIcon.Mode.Normal).isNull()
        assert not icon.pixmap(QSize(24, 24), QIcon.Mode.Disabled).isNull()
