# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Ports tests (T6a): BuildKernel satisfies ExportableKernel.

Importing mycad.geom loads build123d (slow) — expected for this module.
"""

from __future__ import annotations

from mycad.core.ports import ExportableKernel
from mycad.geom.kernel import BuildKernel


def test_build_kernel_satisfies_exportable_kernel() -> None:
    assert isinstance(BuildKernel(), ExportableKernel)


def test_build_kernel_is_assignable_to_exportable_kernel() -> None:
    kernel: ExportableKernel = BuildKernel()
    assert callable(kernel.apply)
