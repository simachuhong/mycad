# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
from .gp import gp_Pnt

class TColgp_Array1OfPnt:
    def __init__(self, lower: int, upper: int) -> None: ...
    def SetValue(self, index: int, value: gp_Pnt) -> None: ...
