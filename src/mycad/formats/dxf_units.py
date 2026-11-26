# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Display precision when converting DXF length units to millimetres."""

import math
from decimal import Decimal


def scaled_length_precision(precision: int, scale: float) -> int:
    """Preserve representable decimal resolution, subject to the eight-place limit."""
    if not 0 <= precision <= 8 or not math.isfinite(scale) or scale <= 0:
        raise ValueError("尺寸精度或单位比例无效")
    exponent = Decimal(str(scale)).normalize().as_tuple().exponent
    if not isinstance(exponent, int):
        raise ValueError("尺寸单位比例无效")
    return min(8, precision + max(0, -exponent))
