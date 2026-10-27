# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
from .Geom import Geom_BSplineCurve
from .TopoDS import TopoDS_Edge

class BRepBuilderAPI_MakeEdge:
    def __init__(self, curve: Geom_BSplineCurve) -> None: ...
    def Edge(self) -> TopoDS_Edge: ...
