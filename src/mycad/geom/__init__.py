# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Sealed geometry adapter package (the only product code importing build123d).

Public surface: the :class:`BuildKernel` facade plus re-exports of the
neutral selector descriptors (defined once in ``mycad.core.selectors``).
"""

from __future__ import annotations

from mycad.geom.kernel import EXPECTED_B123D_VERSION, BuildKernel
from mycad.geom.selectors import EdgeSelector, FaceSelector

__all__ = [
    "BuildKernel",
    "EdgeSelector",
    "EXPECTED_B123D_VERSION",
    "FaceSelector",
]
