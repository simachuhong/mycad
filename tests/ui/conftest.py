# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""GUI test environment: offscreen by default, per-test override allowed.

The env gate lives here (conftest, evaluated before test modules import
Qt) rather than pytest.ini: ini cannot set environment variables without
pulling in the pytest-env dependency, and ``setdefault`` preserves the
override hook the todo-9 Windows-native fallback relies on (plan todo 4
spells out this exact mechanism). An explicit ``qapp`` fixture is not
needed — pytest-qt already provides the session-scoped one.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
