# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for mycad.formats.base and the built-in provider constants (T8a)."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from pathlib import Path

import pytest

from mycad.core.exceptions import EmptyGeometryError
from mycad.core.geometry_types import MassProperties
from mycad.core.ports import ExportableKernel, FormatPort
from mycad.formats.base import FormatProvider, ImportKind
from mycad.formats.providers import STEP_PROVIDER, STL_PROVIDER
from mycad.geom.kernel import BuildKernel

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src" / "mycad"


class _FakeKernel:
    """Minimal structural ExportableKernel for writer-injection tests."""

    def reset(self) -> None:
        return None

    def apply(self, command_id: str, params: Mapping[str, object]) -> None:
        return None

    def mass_properties(self) -> MassProperties:
        raise AssertionError("mass_properties is not used by these tests")

    def export_step(self, path: Path) -> None:
        return None

    def export_stl(self, path: Path) -> None:
        return None


def test_step_provider_fields_are_pinned() -> None:
    assert STEP_PROVIDER.name == "STEP"
    assert STEP_PROVIDER.vendor == "OCC"
    assert STEP_PROVIDER.priority == 100
    assert STEP_PROVIDER.extensions == (".step",)
    assert STEP_PROVIDER.can_read is False
    assert STEP_PROVIDER.can_write is True
    assert STEP_PROVIDER.target == "shape"


def test_stl_provider_fields_are_pinned() -> None:
    assert STL_PROVIDER.name == "STL"
    assert STL_PROVIDER.vendor == "OCC"
    assert STL_PROVIDER.priority == 100
    assert STL_PROVIDER.extensions == (".stl",)
    assert STL_PROVIDER.can_read is False
    assert STL_PROVIDER.can_write is True
    assert STL_PROVIDER.target == "shape"


def test_providers_structurally_implement_format_port() -> None:
    assert isinstance(STEP_PROVIDER, FormatPort)
    assert isinstance(STL_PROVIDER, FormatPort)
    for attribute in ("name", "vendor", "priority", "extensions", "can_write", "write"):
        assert hasattr(STEP_PROVIDER, attribute)
        assert hasattr(STL_PROVIDER, attribute)


def test_write_delegates_to_the_injected_writer(tmp_path: Path) -> None:
    calls: list[tuple[ExportableKernel, Path]] = []

    def recorder(geometry: ExportableKernel, path: Path) -> None:
        calls.append((geometry, path))

    provider = FormatProvider(
        name="REC",
        vendor="TEST",
        priority=1,
        extensions=(".rec",),
        can_read=False,
        can_write=True,
        target="shape",
        _writer=recorder,
    )
    fake = _FakeKernel()
    target = tmp_path / "out.rec"
    provider.write(fake, target)
    assert len(calls) == 1
    assert calls[0] == (fake, target)


def test_import_kind_vocabulary_has_three_members() -> None:
    assert ImportKind.DUMB_SOLID.value == "dumb_solid"
    assert ImportKind.ASSEMBLY_WITH_ATTRS.value == "assembly_with_attrs"
    assert ImportKind.EDITABLE_FEATURES.value == "editable_features"
    assert len(ImportKind) == 3


@pytest.mark.parametrize("fmt", ["step", "stl"])
def test_empty_kernel_export_raises_and_writes_no_file(tmp_path: Path, fmt: str) -> None:
    kernel = BuildKernel()
    target = tmp_path / f"empty.{fmt}"
    with pytest.raises(EmptyGeometryError):
        if fmt == "step":
            kernel.export_step(target)
        else:
            kernel.export_stl(target)
    assert not target.exists()


def test_no_src_code_path_returns_editable_features() -> None:
    """Plan guard: EDITABLE_FEATURES is vocabulary only — no usage site in src."""

    offenders: list[Path] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "EDITABLE_FEATURES":
                offenders.append(path)
    assert not offenders, f"EDITABLE_FEATURES referenced in src: {offenders}"
