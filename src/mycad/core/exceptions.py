# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Closed exception taxonomy for MyCAD (Phase 0, 15 classes).

The taxonomy is a Wave 0 invariant: T1 locks the count to exactly 15. Any
addition must come with a Momus round that re-approves the expansion. The
two ordinal-bearing classes (TopologyReferenceError, GeometryBuildError)
record the ordinal of the offending operation so batch tools can map the
exception back to the failing step in a plan.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MycadError(RuntimeError):
    """Base class for every MyCAD-raised error.

    Subclasses set their own positional fields; ``message`` is the only
    shared one. ``command_id`` is the optional identifier of the command
    that triggered the failure (None for batch-level or bootstrap errors).
    """

    message: str
    command_id: str | None = None

    def __str__(self) -> str:  # pragma: no cover - trivial
        if self.command_id is None:
            return self.message
        return f"{self.message} (command_id={self.command_id!r})"


# ---------------------------------------------------------------------------
# 15 closed classes — order is intentional and part of the public contract
# (test_exceptions.py pins the order via ``MycadError.__subclasses__()``).
# ---------------------------------------------------------------------------


@dataclass
class ValidationError(MycadError):
    """Input validation failed before any geometry work began."""


@dataclass
class TopologyReferenceError(MycadError):
    """Selector or face/edge reference could not be resolved.

    ``ordinal`` records the operation index in the plan that produced the
    bad reference, when known.
    """

    ordinal: int | None = None


@dataclass
class GeomVersionError(MycadError):
    """Geometry archive schema version mismatch."""


@dataclass
class GeometryBuildError(MycadError):
    """Primitive construction failed (boolean, fillet, extrude, ...).

    ``ordinal`` records the failing operation index, when known.
    """

    ordinal: int | None = None


@dataclass
class CommandConflictError(MycadError):
    """Two commands in the same plan attempt to mutate the same target."""


@dataclass
class EmptyGeometryError(MycadError):
    """Operation produced a zero-volume solid."""


@dataclass
class ArchiveVersionError(MycadError):
    """Project archive (.mycad) version is not supported.

    ``found`` / ``supported`` follow the #round9-NB-E fill rules: on a
    format mismatch ``found`` is the archive's actual format string (the
    ``"missing"`` placeholder when the key is absent or not a string) and
    ``supported`` is ``"mycad.document"``; on a version mismatch ``found``
    is the archive's version rendered as a string (e.g. ``"99"``) and
    ``supported`` is ``1``. The two scenarios are asserted with their own
    field pairs and must never be mixed.
    """

    found: str = ""
    supported: str | int = ""


@dataclass
class UnknownFormatError(MycadError):
    """No registered provider can read/write the requested format."""


@dataclass
class CliSyntaxError(MycadError):
    """Command-line argument parser rejected the input."""


@dataclass
class InvalidPlanTransition(MycadError):
    """Plan state machine cannot perform the requested transition."""


@dataclass
class InvalidHistoryError(MycadError):
    """History log entry is malformed or out of order."""


@dataclass
class BatchRollbackError(MycadError):
    """A batch failed and was rolled back to its pre-batch state."""

    failed_ordinal: int = -1
    failed_command_id: str = ""
    reason: str = ""
    executed_ids: tuple[str, ...] = ()


@dataclass
class ReplayDuringRollbackError(MycadError):
    """Replay was attempted while a rollback is in flight."""

    original: BaseException | None = None
    replay_reason: str = ""


@dataclass
class UnknownCommandError(MycadError):
    """A plan referenced a command identifier unknown to the registry."""

    identifier: str = ""


@dataclass
class ProviderConflictError(MycadError):
    """Two providers claim responsibility for the same file extension.

    ``extension`` is the dotted suffix (e.g. ``.step``). ``provider1`` /
    ``provider2`` are ``(name, vendor)`` tuples so the user sees both the
    provider name and the importing vendor.
    """

    extension: str = ""
    provider1: tuple[str, str] = field(default=("", ""))
    provider2: tuple[str, str] = field(default=("", ""))


# All 15 subclasses — exported for tests that lock the taxonomy.
__all__ = [
    "MycadError",
    "ValidationError",
    "TopologyReferenceError",
    "GeomVersionError",
    "GeometryBuildError",
    "CommandConflictError",
    "EmptyGeometryError",
    "ArchiveVersionError",
    "UnknownFormatError",
    "CliSyntaxError",
    "InvalidPlanTransition",
    "InvalidHistoryError",
    "BatchRollbackError",
    "ReplayDuringRollbackError",
    "UnknownCommandError",
    "ProviderConflictError",
]
