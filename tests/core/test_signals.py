# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Headless signal bus tests."""

from __future__ import annotations

import gc
import subprocess
import sys
import typing
from collections.abc import Mapping

import pytest

from mycad.core.signals import SignalBus, SignalName

EXPECTED_NINE = (
    "pre_command",
    "post_command",
    "command_amended",
    "metadata_changed",
    "named_group_added",
    "named_group_removed",
    "document_saving",
    "document_saved",
    "geometry_rebuilt",
)


def test_signal_name_tuple_lock() -> None:
    """The Literal exposes exactly nine names, in the spec's order."""
    args = typing.get_args(SignalName)
    assert isinstance(args, tuple)
    assert args == EXPECTED_NINE


def test_emit_reaches_subscriber_and_counts() -> None:
    bus = SignalBus()
    calls: list[object] = []
    bus.subscribe("post_command", calls.append)
    bus.emit("post_command", {"ordinal": 1})
    bus.emit("post_command", {"ordinal": 2})
    assert calls == [{"ordinal": 1}, {"ordinal": 2}]


def test_emit_without_payload_delivers_empty_mapping() -> None:
    bus = SignalBus()
    calls: list[object] = []
    bus.subscribe("geometry_rebuilt", calls.append)
    bus.emit("geometry_rebuilt")
    assert calls == [{}]


def test_emit_is_scoped_to_subscribed_name() -> None:
    bus = SignalBus()
    got: list[object] = []
    bus.subscribe("pre_command", got.append)
    bus.emit("post_command", {"x": 1})
    assert got == []


def test_listener_exception_is_isolated() -> None:
    """One failing listener warns; others still run; emit returns normally."""

    bus = SignalBus()
    got: list[object] = []

    def boom(payload: Mapping[str, object]) -> None:
        raise RuntimeError("listener exploded")

    bus.subscribe("metadata_changed", boom)
    bus.subscribe("metadata_changed", got.append)
    with pytest.warns(RuntimeWarning):
        bus.emit("metadata_changed", {"k": "v"})
    assert got == [{"k": "v"}]


def test_dead_subscriber_is_dropped() -> None:
    """Subscribers are held weakly; garbage-collected ones disappear."""

    bus = SignalBus()
    got: list[object] = []
    bus.subscribe("document_saved", got.append)

    def transient(payload: Mapping[str, object]) -> None:
        got.append(payload)

    bus.subscribe("document_saved", transient)
    del transient
    gc.collect()
    bus.emit("document_saved", {"n": 1})
    assert got == [{"n": 1}]


def test_signals_pull_in_no_gui_or_event_libraries() -> None:
    """Zero Qt / third-party event-bus dependencies."""
    code = (
        "import sys; import mycad.core.signals; "
        'bad = {"PyQt5", "PyQt6", "PySide2", "PySide6", "blinker", "zope"} '
        "& set(sys.modules); print(','.join(sorted(bad)))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert not result.stdout.strip(), f"signals leaked GUI/event modules: {result.stdout.strip()!r}"
