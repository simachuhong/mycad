# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Version-gate tests for the build123d kernel adapter.

The gate reads the version from ``importlib.metadata.version`` (the unique
version source). Monkeypatching ``build123d.__version__`` must have no
effect because the implementation never reads that attribute.
"""

from __future__ import annotations

import importlib

import pytest

from mycad.core.exceptions import GeomVersionError
from mycad.geom.kernel import EXPECTED_B123D_VERSION, assert_b123d_version


def _version_999(_name: str) -> str:
    return "9.9.9"


def _version_011(_name: str) -> str:
    return "0.11"


def test_gate_passes_for_pinned_version() -> None:
    assert_b123d_version()
    assert_b123d_version(".".join(str(part) for part in EXPECTED_B123D_VERSION))


def test_gate_mismatch_raises_with_actual_and_expected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("importlib.metadata.version", _version_999)
    with pytest.raises(GeomVersionError) as excinfo:
        assert_b123d_version()
    message = str(excinfo.value)
    assert "9.9.9" in message
    assert "0.11.1" in message


def test_gate_unparseable_version_raises_with_actual_and_expected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("importlib.metadata.version", _version_011)
    with pytest.raises(GeomVersionError) as excinfo:
        assert_b123d_version()
    message = str(excinfo.value)
    assert "'0.11'" in message
    assert "0.11.1" in message


@pytest.mark.parametrize(
    ("raw", "fragment"),
    [
        ("9.9.9", "9.9.9"),
        ("0.11", "0.11"),
        ("1.2.3.4", "1.2.3.4"),
        ("abc", "abc"),
        ("0.11.x", "0.11.x"),
    ],
)
def test_gate_rejects_bad_raw_strings(raw: str, fragment: str) -> None:
    with pytest.raises(GeomVersionError) as excinfo:
        assert_b123d_version(raw)
    assert fragment in str(excinfo.value)


def test_gate_trips_at_module_import(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("importlib.metadata.version", _version_999)
    kernel_module = importlib.import_module("mycad.geom.kernel")
    with pytest.raises(GeomVersionError):
        importlib.reload(kernel_module)
    monkeypatch.undo()
    importlib.reload(kernel_module)
