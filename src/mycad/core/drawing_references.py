# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Durable drawing references describe geometry, never runtime topology IDs."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

ReferenceStatus = Literal["resolved", "orphaned", "ambiguous"]


@dataclass(frozen=True, slots=True)
class DrawingGeometryReference:
    """Bounded source predicate plus the requested projected point/curve role.

    An optional original command audit key narrows the owner; geometry must
    still resolve uniquely after replay. A curve index is deliberately absent.
    """

    kind: Literal["cylindrical_face", "planar_face", "edge"]
    parameters: tuple[tuple[str, float], ...] = ()
    owner_command: str | None = None
    role: Literal["geometry", "start", "end", "center"] = "geometry"

    def __post_init__(self) -> None:
        if self.kind not in ("cylindrical_face", "planar_face", "edge"):
            raise ValueError("unsupported drawing reference kind")
        if self.role not in ("geometry", "start", "end", "center"):
            raise ValueError("unsupported drawing reference role")
        names = [key for key, _ in self.parameters]
        if len(set(names)) != len(names) or any(not name for name in names):
            raise ValueError("reference predicate names must be unique and nonempty")
        if any(isinstance(value, bool) or not math.isfinite(value) for _, value in self.parameters):
            raise ValueError("reference predicates must be finite numbers")


@dataclass(frozen=True, slots=True)
class ReferenceResolution:
    status: ReferenceStatus
    curve_ids: tuple[str, ...] = ()
    message: str = ""

    def __post_init__(self) -> None:
        if self.status not in ("resolved", "orphaned", "ambiguous"):
            raise ValueError("invalid reference status")
        if (self.status == "resolved") != bool(self.curve_ids):
            raise ValueError("only uniquely resolved references carry projected curves")
