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
    """

    def __init__(self) -> None:
        self._refs: dict[SignalName, list[_CallbackRef]] = {}

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

    def emit(self, name: SignalName, payload: SignalPayload | None = None) -> None:
        """Deliver ``payload`` (empty mapping when omitted) to ``name`` subscribers.

        A listener that raises is reduced to a ``RuntimeWarning`` so one
        broken subscriber cannot abort the remaining listeners or the caller.
        """
        delivered: SignalPayload = {} if payload is None else payload
        for ref in self._refs.get(name, []):
            callback = ref()
            if callback is None:
                continue
            try:
                callback(delivered)
            except Exception:
                warnings.warn(
                    f"signal listener for {name!r} raised; continuing",
                    RuntimeWarning,
                    stacklevel=2,
                )
