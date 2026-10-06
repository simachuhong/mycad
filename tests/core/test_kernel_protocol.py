# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Kernel protocol tests (T6a step 0).

The Kernel protocol is the core-side dependency inversion: core holds only
the Protocol and never imports geom. These tests use a scripted FakeKernel
(no build123d) so they stay fast and headless.
"""

from __future__ import annotations

from collections.abc import Mapping

from mycad.core.kernel_protocol import Kernel


class FakeKernel:
    """Scripted kernel: records calls, owns no geometry."""

    def __init__(self) -> None:
        self.reset_count = 0
        self.calls: list[tuple[str, dict[str, object]]] = []

    def reset(self) -> None:
        self.reset_count += 1

    def apply(self, command_id: str, params: Mapping[str, object]) -> None:
        self.calls.append((command_id, dict(params)))


def test_fake_kernel_satisfies_kernel_protocol() -> None:
    assert isinstance(FakeKernel(), Kernel)


def test_kernel_protocol_requires_both_methods() -> None:
    class ResetOnly:
        def reset(self) -> None: ...

    class ApplyOnly:
        def apply(self, command_id: str, params: Mapping[str, object]) -> None: ...

    assert not isinstance(ResetOnly(), Kernel)
    assert not isinstance(ApplyOnly(), Kernel)
