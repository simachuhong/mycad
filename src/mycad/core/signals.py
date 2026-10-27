# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Minimal headless signal bus (stdlib only, zero Qt / third-party deps).

Single-threaded by design (see the phase 0 plan's "Must NOT do" list): the
document model takes no write lock and the bus does not synchronise. A
listener that raises is isolated — the exception is reduced to a warning so
one broken plugin cannot abort the main flow (plugin isolation groundwork
for T9).
"""

from __future__ import annotations

import types
import warnings
import weakref
from collections.abc import Callable, Mapping
from contextlib import suppress
from typing import Literal, cast

SignalName = Literal[
    "pre_command",
    "post_command",
    "command_amended",
    "metadata_changed",
    "named_group_added",
    "named_group_removed",
    "document_saving",
    "document_saved",
    "geometry_rebuilt",
]

SignalPayload = Mapping[str, object]
SignalCallback = Callable[[SignalPayload], None]

# weakref.ref, weakref.WeakMethod and the builtin-adapter below are all
# callables returning the live callback (or None once dead).
_CallbackRef = Callable[[], SignalCallback | None]


class _BoundBuiltinRef:
    """Weak handle to a bound *builtin* method (e.g. ``list.append``).

    ``weakref.ref(calls.append)`` would die immediately — the wrapper is
    ephemeral. Instead weakly track ``__self__`` and rebind by name.
    """

    __slots__ = ("_self_ref", "_name")

    def __init__(self, meth: types.BuiltinMethodType) -> None:
        self._self_ref = weakref.ref(meth.__self__)
        self._name = meth.__name__

    def __call__(self) -> SignalCallback | None:
        inst = self._self_ref()
        if inst is None:
            return None
        return cast("SignalCallback | None", getattr(inst, self._name))


def _make_ref(callback: SignalCallback) -> _CallbackRef:
    if isinstance(callback, types.MethodType):
        return weakref.WeakMethod(callback)
    if isinstance(callback, types.BuiltinMethodType):
        return _BoundBuiltinRef(callback)
    return weakref.ref(callback)


class SignalBus:
    """Per-name weak subscription lists with isolated, synchronous delivery.

    One subscription list per signal name. Callbacks are held weakly (via
    :func:`_make_ref`); dead references are silently dropped at delivery.
    The Bus can defer commit notifications in a transaction and discard them
    after rolling document state back; explicit attempt notifications can
    still be delivered immediately.
    """

    def __init__(self) -> None:
        self._refs: dict[SignalName, list[_CallbackRef]] = {}
        self._pending: list[tuple[SignalName, SignalPayload]] | None = None

    def subscribe(self, name: SignalName, callback: SignalCallback) -> None:
        """Register ``callback`` under ``name``, held weakly where possible."""
        try:
            ref: _CallbackRef = _make_ref(callback)
        except TypeError:
            # Builtin owners like ``list`` are not weak-referenceable; hold strongly.
            def strong_ref() -> SignalCallback:
                return callback

            ref = strong_ref
        self._refs.setdefault(name, []).append(ref)

    def begin_transaction(self) -> None:
        """Buffer events until the surrounding Bus operation commits."""
        if self._pending is not None:
            raise RuntimeError("signal transaction is already active")
        self._pending = []

    def commit_transaction(self) -> None:
        """Deliver buffered events in order after state has committed."""
        if self._pending is None:
            raise RuntimeError("no active signal transaction")
        pending = self._pending
        self._pending = None
        for name, payload in pending:
            self._deliver(name, payload)

    def discard_transaction(self) -> None:
        """Drop events from an operation whose state was rolled back."""
        if self._pending is None:
            raise RuntimeError("no active signal transaction")
        self._pending = None

    def emit(self, name: SignalName, payload: SignalPayload | None = None) -> None:
        """Deliver ``payload`` (empty mapping when omitted) to ``name`` subscribers.

        A listener that raises is reduced to a ``RuntimeWarning`` so one
        broken subscriber cannot abort the remaining listeners or the caller.
        """
        delivered: SignalPayload = {} if payload is None else payload
        if self._pending is not None:
            self._pending.append((name, dict(delivered)))
            return
        self._deliver(name, delivered)

    def emit_immediate(self, name: SignalName, payload: SignalPayload | None = None) -> None:
        """Deliver an attempt notification immediately, even in a transaction."""
        self._deliver(name, {} if payload is None else payload)

    def _deliver(self, name: SignalName, delivered: SignalPayload) -> None:
        """Deliver one event while isolating listener failures."""
        for ref in self._refs.get(name, []):
            callback = ref()
            if callback is None:
                continue
            try:
                callback(delivered)
            except Exception:
                with suppress(Warning):
                    warnings.warn(
                        f"signal listener for {name!r} raised; continuing",
                        RuntimeWarning,
                        stacklevel=2,
                    )
