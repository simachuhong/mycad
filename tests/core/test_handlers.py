# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Command handler contract tests (T6a).

BuiltinModelingHandler binds one command id per instance and forwards to
``ctx.kernel.apply``; the ctx-injected command id must match the bound id.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from mycad.core.handlers import (
    BuiltinModelingHandler,
    CommandHandler,
    HandlerContext,
)


class FakeKernel:
    """Scripted kernel: records apply() calls, owns no geometry."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def reset(self) -> None: ...

    def apply(self, command_id: str, params: Mapping[str, object]) -> None:
        self.calls.append((command_id, dict(params)))


def test_builtin_handler_satisfies_command_handler_protocol() -> None:
    assert isinstance(BuiltinModelingHandler("box.create"), CommandHandler)


def test_command_id_is_bound_per_instance_not_class_attribute() -> None:
    h1 = BuiltinModelingHandler("box.create")
    h2 = BuiltinModelingHandler("sphere.create")
    assert h1.command_id == "box.create"
    assert h2.command_id == "sphere.create"
    assert "command_id" not in vars(BuiltinModelingHandler)


def test_handle_applies_via_kernel_and_returns_none() -> None:
    kernel = FakeKernel()
    handler = BuiltinModelingHandler("box.create")
    ctx = HandlerContext(kernel=kernel, command_id="box.create")
    params: dict[str, object] = {"length": 1.0}

    result = handler.handle(params, ctx)

    assert result is None
    assert kernel.calls == [("box.create", {"length": 1.0})]


def test_handle_rejects_ctx_command_id_mismatch() -> None:
    kernel = FakeKernel()
    handler = BuiltinModelingHandler("box.create")
    wrong_ctx = HandlerContext(kernel=kernel, command_id="sphere.create")

    with pytest.raises(ValueError, match="command_id"):
        handler.handle({}, wrong_ctx)

    assert kernel.calls == []
