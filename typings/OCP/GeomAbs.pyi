# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
from typing import ClassVar

class GeomAbs_CurveType:
    GeomAbs_Line: ClassVar[GeomAbs_CurveType]
    GeomAbs_Circle: ClassVar[GeomAbs_CurveType]
    GeomAbs_Ellipse: ClassVar[GeomAbs_CurveType]
    GeomAbs_BSplineCurve: ClassVar[GeomAbs_CurveType]
