# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
from .TopoDS import TopoDS_Shape

class BRepLib:
    @staticmethod
    def BuildCurves3d_s(shape: TopoDS_Shape, tolerance: float) -> bool: ...
