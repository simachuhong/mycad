# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for mycad.formats.registry (T8a)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from mycad.core.exceptions import ProviderConflictError, UnknownFormatError
from mycad.core.ports import ExportableKernel, FormatPort
from mycad.formats.base import FormatProvider
from mycad.formats.providers import STEP_PROVIDER, STL_PROVIDER
from mycad.formats.registry import FormatProviderRegistry
from mycad.geom.kernel import BuildKernel

BOX_PARAMS: Mapping[str, object] = {"size_x": 30.0, "size_y": 20.0, "size_z": 10.0}


def _noop_writer(geometry: ExportableKernel, path: Path) -> None:
    return None


def _fake_provider(
    extensions: tuple[str, ...],
    priority: int,
    name: str = "FAKE",
    vendor: str = "TEST",
) -> FormatProvider:
    return FormatProvider(
        name=name,
        vendor=vendor,
        priority=priority,
        extensions=extensions,
        can_read=False,
        can_write=True,
        target="shape",
        _writer=_noop_writer,
    )


def _registry() -> FormatProviderRegistry:
    return FormatProviderRegistry([STEP_PROVIDER, STL_PROVIDER])


def test_get_by_extension_resolves_registered_providers() -> None:
    registry = _registry()
    assert registry.get_by_extension(".step") is STEP_PROVIDER
    assert registry.get_by_extension(".stl") is STL_PROVIDER
    assert registry.get_by_extension("STEP") is STEP_PROVIDER
    with pytest.raises(UnknownFormatError):
        registry.get_by_extension(".stp")


@pytest.mark.parametrize("ext", [".x_t", ".dwg"])
def test_unknown_extension_raises_without_support_claim(ext: str) -> None:
    registry = _registry()
    with pytest.raises(UnknownFormatError) as excinfo:
        registry.get_by_extension(ext)
    message = str(excinfo.value)
    assert ext in message
    assert "support" not in message.lower()


def test_lowest_priority_provider_wins() -> None:
    registry = _registry()
    preferred = _fake_provider((".step",), 50)
    registry.register(preferred)
    assert registry.get_by_extension(".step") is preferred
    assert registry.get_by_extension(".stl") is STL_PROVIDER


def test_same_priority_extension_overlap_raises_conflict() -> None:
    registry = FormatProviderRegistry()
    registry.register(_fake_provider((".step",), 100, name="FIRST", vendor="V1"))
    with pytest.raises(ProviderConflictError) as excinfo:
        registry.register(_fake_provider((".stp", ".step"), 100, name="SECOND", vendor="V2"))
    error = excinfo.value
    assert error.extension == ".step"
    assert error.provider1 == ("FIRST", "V1")
    assert error.provider2 == ("SECOND", "V2")


def test_same_priority_disjoint_extensions_do_not_conflict() -> None:
    registry = FormatProviderRegistry()
    registry.register(_fake_provider((".step",), 100, name="A", vendor="V"))
    registry.register(_fake_provider((".stl",), 100, name="B", vendor="V"))
    assert len(registry.list_providers()) == 2


def test_list_providers_keeps_registration_order() -> None:
    extra = _fake_provider((".obj",), 100)
    registry = FormatProviderRegistry([STEP_PROVIDER, extra, STL_PROVIDER])
    assert registry.list_providers() == (STEP_PROVIDER, extra, STL_PROVIDER)


def test_resolve_returns_a_format_port(tmp_path: Path) -> None:
    registry = _registry()
    assert isinstance(registry.resolve(tmp_path / "f.step"), FormatPort)
    assert isinstance(registry.resolve(tmp_path / "f.stl"), FormatPort)


@pytest.mark.parametrize("filename", ["f.step", "f.stl"])
def test_resolve_write_end_to_end(tmp_path: Path, filename: str) -> None:
    kernel = BuildKernel()
    kernel.apply("feature.box", BOX_PARAMS)
    target = tmp_path / filename
    registry = _registry()
    registry.resolve(target).write(kernel, target)
    assert target.exists()
    assert target.stat().st_size > 0
