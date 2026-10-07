# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Agent plan types — protocol placeholder, phase 0 re-exports types only.

协议占位：阶段 0 仅类型再导出。The plan lifecycle is owned by
``mycad.core``; every state transition is a ``Plan`` method (there are no
free transition functions to re-export), so this module exposes the
aggregate, its step type and the transition exception. No network, no
LLM, no tool-schema generation lives in this package (ADR-004 defers
the tool surface to phase 2).
"""

from __future__ import annotations

from mycad.core.exceptions import InvalidPlanTransition
from mycad.core.plan import Plan, PlannedCommand

__all__ = ["InvalidPlanTransition", "Plan", "PlannedCommand"]
