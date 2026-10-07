# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Plugin manifest resolution (T9a).

The single authority for ``PluginManifest`` and the API constants is
``mycad.plugins.types`` (#round9-4/#round9-5); this module imports them
and only implements the manifest location algorithm pinned there: read
the module attribute ``manifest`` (dict / zero-arg callable /
dataclass instance), normalize and validate it, then gate on the
api_version major. Skip-reason codes are derived from the contract
Literal, never spelled out as literals here.
"""

from __future__ import annotations

import re
from typing import TypeGuard, get_args

from mycad.plugins.types import CURRENT_API_MAJOR, WARNING_REASON, PluginManifest


def _is_dict(value: object) -> TypeGuard[dict[object, object]]:
    """Narrow ``object`` to a fully-typed dict (isinstance alone yields Unknown)."""

    return isinstance(value, dict)


def _is_list_or_tuple(value: object) -> TypeGuard[list[object] | tuple[object, ...]]:
    """Narrow ``object`` to a list/tuple with ``object`` elements."""

    return isinstance(value, (list, tuple))


#: Derived from the contract Literal's source order (its first member is
#: the no-manifest code); manager.py uses the same derivation shape.
_MISSING_MANIFEST: str = get_args(WARNING_REASON)[0]
_DAMAGED_MANIFEST: str = get_args(WARNING_REASON)[1]
_API_MISMATCH: str = get_args(WARNING_REASON)[2]

_ID_PATTERN = re.compile(r"^[a-z0-9_.-]+$")
_REQUIRED_KEYS: frozenset[str] = frozenset({"id", "version", "api_version"})
_KNOWN_KEYS: frozenset[str] = _REQUIRED_KEYS | frozenset({"permissions", "homepage"})


def resolve_manifest(module: object) -> tuple[PluginManifest | None, str | None]:
    """Resolve a plugin module's ``manifest`` attribute to a manifest.

    Returns ``(manifest, None)`` on success, else ``(None, reason)``
    with a reason code from the contract vocabulary: the attribute is
    absent, damaged beyond repair, or built against an incompatible
    api_version major. Callable forms are invoked exactly once.
    """
    raw: object = getattr(module, "manifest", None)
    if raw is None:
        return None, _MISSING_MANIFEST
    if _is_dict(raw):
        return _from_dict(raw)
    if isinstance(raw, PluginManifest):
        return _gate(raw)
    if callable(raw):
        try:
            called: object = raw()
        except Exception:
            return None, _DAMAGED_MANIFEST
        if _is_dict(called):
            return _from_dict(called)
        if isinstance(called, PluginManifest):
            return _gate(called)
        return None, _DAMAGED_MANIFEST
    return None, _DAMAGED_MANIFEST


def _gate(manifest: PluginManifest) -> tuple[PluginManifest | None, str | None]:
    """Apply the api-major gate to an already-built manifest instance.

    The ValueError arm covers unparseable majors; AttributeError covers
    a non-str ``api_version`` smuggled past the dataclass typing.
    """
    try:
        major = int(manifest.api_version.split(".", 1)[0])
    except (AttributeError, ValueError):
        return None, _API_MISMATCH
    if major != CURRENT_API_MAJOR:
        return None, _API_MISMATCH
    return manifest, None


def _from_dict(data: dict[object, object]) -> tuple[PluginManifest | None, str | None]:
    """Validate a dict payload and build a manifest from it.

    Ordering pinned by the plan: key-set check, then the api gate
    (api_version is parsed before any other field's validity is
    judged), then the remaining fields.
    """
    keys: set[object] = set(data.keys())
    if not _REQUIRED_KEYS <= keys or keys - _KNOWN_KEYS:
        return None, _DAMAGED_MANIFEST
    api_value: object = data["api_version"]
    if not isinstance(api_value, str) or not api_value:
        return None, _DAMAGED_MANIFEST
    try:
        major = int(api_value.split(".", 1)[0])
    except ValueError:
        return None, _API_MISMATCH
    if major != CURRENT_API_MAJOR:
        return None, _API_MISMATCH
    plugin_id: object = data["id"]
    if not isinstance(plugin_id, str) or not plugin_id or not _ID_PATTERN.match(plugin_id):
        return None, _DAMAGED_MANIFEST
    version: object = data["version"]
    if not isinstance(version, str) or not version:
        return None, _DAMAGED_MANIFEST
    permissions = _permissions_from(data.get("permissions", ()))
    if permissions is None:
        return None, _DAMAGED_MANIFEST
    homepage: object = data.get("homepage", "")
    if not isinstance(homepage, str):
        return None, _DAMAGED_MANIFEST
    return (
        PluginManifest(
            id=plugin_id,
            version=version,
            api_version=api_value,
            permissions=permissions,
            homepage=homepage,
        ),
        None,
    )


def _permissions_from(raw: object) -> tuple[str, ...] | None:
    """Normalize an optional permissions list/tuple; None when invalid."""
    if not _is_list_or_tuple(raw):
        return None
    items: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            return None
        items.append(item)
    return tuple(items)


__all__ = ["resolve_manifest"]
