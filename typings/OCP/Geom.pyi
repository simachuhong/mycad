# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
from .gp import gp_Pnt
from .TColgp import TColgp_Array1OfPnt
from .TColStd import TColStd_Array1OfInteger, TColStd_Array1OfReal

class Geom_BSplineCurve:
    def __init__(
        self,
        poles: TColgp_Array1OfPnt,
        weights: TColStd_Array1OfReal,
        knots: TColStd_Array1OfReal,
        multiplicities: TColStd_Array1OfInteger,
        degree: int,
    ) -> None: ...
    def Degree(self) -> int: ...
    def IsRational(self) -> bool: ...
    def Weight(self, index: int) -> float: ...
    def Value(self, parameter: float) -> gp_Pnt: ...
