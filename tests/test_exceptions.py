# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Closed 15-class exception taxonomy tests."""

from __future__ import annotations

import dataclasses

from mycad.core import exceptions

EXPECTED_NAMES: list[str] = [
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


def test_exactly_fifteen_subclasses() -> None:
    subclasses = exceptions.MycadError.__subclasses__()
    names = sorted(cls.__name__ for cls in subclasses)
    expected_sorted = sorted(EXPECTED_NAMES)
    assert names == expected_sorted, f"taxonomy drift: have {names}, want {expected_sorted}"
    assert len(subclasses) == 15


def test_ordinal_field_present_on_required_classes() -> None:
    """TopologyReferenceError and GeometryBuildError carry ordinal field."""

    for cls in (exceptions.TopologyReferenceError, exceptions.GeometryBuildError):
        fields = {f.name for f in dataclasses.fields(cls)}
        assert "ordinal" in fields, f"{cls.__name__} missing ordinal"
        assert "message" in fields
        assert "command_id" in fields


def test_unknown_command_error_carries_identifier() -> None:
    """UnknownCommandError declares an ``identifier`` field."""

    fields = {f.name: f for f in dataclasses.fields(exceptions.UnknownCommandError)}
    assert "identifier" in fields, "UnknownCommandError must declare identifier"


def test_provider_conflict_error_signature() -> None:
    """ProviderConflictError takes (extension, provider1, provider2)."""

    fields = {f.name for f in dataclasses.fields(exceptions.ProviderConflictError)}
    expected = {"message", "command_id", "extension", "provider1", "provider2"}
    assert fields == expected, (
        f"ProviderConflictError field drift: {sorted(fields)} vs {sorted(expected)}"
    )


def test_command_conflict_error_has_no_identifier() -> None:
    """CommandConflictError does not gain an ``identifier`` slot."""

    fields = {f.name for f in dataclasses.fields(exceptions.CommandConflictError)}
    assert "identifier" not in fields


def test_reject_sixteenth_subclass() -> None:
    """Defining a new MycadError subclass should fail the count invariant."""

    @dataclasses.dataclass
    class SixteenthError(exceptions.MycadError):
        pass

    try:
        subclasses = exceptions.MycadError.__subclasses__()
        names = sorted(cls.__name__ for cls in subclasses)
        assert "SixteenthError" in names
        assert len(subclasses) == 16
    finally:
        del SixteenthError
