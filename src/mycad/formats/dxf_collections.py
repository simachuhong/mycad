# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""DXF entity-handle mappings shared by drawing collection exchange."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from typing import cast

from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef


def is_exact_positive_xy_normal(value: object) -> bool:
    """Accept any finite positive multiple of the world XY normal."""
    try:
        x, y, z = cast("Sequence[object]", value)
    except (TypeError, ValueError):
        return False
    if any(isinstance(item, bool) or not isinstance(item, int | float) for item in (x, y, z)):
        return False
    return x == 0 and y == 0 and math.isfinite(cast("float", z)) and cast("float", z) > 0


def unique_import_name(name: str, used: set[str], *, max_length: int | None = None) -> str:
    """Allocate a deterministic name under the document's casefold rules."""
    candidate, index = name, 1
    while candidate.casefold() in used:
        index += 1
        suffix = f" ({index})"
        candidate = f"{name[: max_length - len(suffix)] if max_length else name}{suffix}"
    return candidate


def _utf8_prefix(value: str, limit: int) -> str:
    return value.encode("utf-8")[:limit].decode("utf-8", errors="ignore")


def collection_export_name(value: str, identity: str, used: set[str], fallback: str) -> str:
    """Return a legal, unique native name within the DXF string limit."""
    from ezdxf.lldxf.validator import is_valid_table_name

    clean = "".join("_" if ord(char) < 32 or ord(char) == 127 else char for char in value)
    base = re.sub(r'[<>/\\\\":;?*|=,`]', "_", clean).strip()
    if not base or not is_valid_table_name(base):
        base = fallback
    candidate = base
    index = 0
    while len(candidate.encode("utf-8")) > 255 or candidate.casefold() in used:
        suffix = "_" + hashlib.sha256(f"{identity}\0{index}".encode()).hexdigest()[:12]
        candidate = _utf8_prefix(base, 255 - len(suffix)).rstrip() + suffix
        index += 1
    return candidate


class DxfObjectMap:
    """Track all native handles for an object, including ambiguous mappings."""

    def __init__(self) -> None:
        self._handles: dict[DrawingObjectRef, tuple[str, ...]] = {}
        self._owners: dict[str, set[DrawingObjectRef]] = {}

    def register(self, ref: DrawingObjectRef, handles: tuple[str, ...]) -> None:
        if ref in self._handles:
            raise ValueError("DXF 对象身份重复映射。")
        normalized = tuple(handle.upper() for handle in handles)
        if (
            not normalized
            or len(set(normalized)) != len(normalized)
            or any(
                not handle or any(char not in "0123456789ABCDEF" for char in handle)
                for handle in normalized
            )
        ):
            raise ValueError("DXF handle 无效或重复。")
        self._handles[ref] = normalized
        for handle in normalized:
            self._owners.setdefault(handle, set()).add(ref)

    def handles_for(self, ref: DrawingObjectRef) -> tuple[str, ...]:
        return self._handles.get(ref, ())

    def resolve_group(
        self, handles: tuple[str, ...]
    ) -> tuple[tuple[DrawingObjectRef, ...], tuple[str, ...]]:
        """Resolve complete, unambiguous objects; return unmatched handles separately."""
        ordered = tuple(dict.fromkeys(handle.upper() for handle in handles))
        present = set(ordered)
        resolved: list[DrawingObjectRef] = []
        covered: set[str] = set()
        for handle in ordered:
            owners = self._owners.get(handle, set())
            if len(owners) != 1:
                continue
            ref = next(iter(owners))
            if ref in resolved:
                continue
            required = self._handles[ref]
            if set(required).issubset(present) and all(
                self._owners[item] == {ref} for item in required
            ):
                resolved.append(ref)
                covered.update(required)
        return tuple(resolved), tuple(handle for handle in ordered if handle not in covered)


def write_native_groups(
    document: object, groups: tuple[DrawingGroup, ...], mapping: DxfObjectMap
) -> tuple[str, ...]:
    """Write model-space GROUPs and report every missing member."""
    from ezdxf.document import Drawing

    drawing = cast("Drawing", document)
    warnings: list[str] = []
    used: set[str] = set()
    for group in groups:
        handles = tuple(
            dict.fromkeys(handle for ref in group.members for handle in mapping.handles_for(ref))
        )
        missing = tuple(ref for ref in group.members if not mapping.handles_for(ref))
        label = group.name or group.group_id[:8]
        if not handles:
            warnings.append(f"组 {label} 没有可导出的成员，未写入 DXF。")
            continue
        if missing:
            warnings.append(f"组 {label} 成员不完整：{len(missing)} 个对象未导出。")
        name = group.name
        if name is not None:
            sanitized = collection_export_name(name, group.group_id, used, "GROUP")
            if sanitized != name:
                warnings.append(f"组 {name} 的 DXF 名称已转换为 {sanitized}。")
            name = sanitized
            used.add(name.casefold())
        description = "".join(
            " " if ord(char) < 32 or ord(char) == 127 else char for char in group.description
        )
        description = _utf8_prefix(description, 255)
        if description != group.description:
            warnings.append(f"组 {label} 的 DXF 说明包含控制字符或过长，已转换或截短。")
        entities = [drawing.entitydb.get(handle) for handle in handles]
        if any(item is None for item in entities):
            raise ValueError("DXF 组引用的导出实体不存在。")
        group_entity = drawing.groups.new(
            name, description=description, selectable=group.selectable
        )
        group_entity.set_data(item for item in entities if item is not None)
    return tuple(warnings)


def read_native_groups(
    document: object, mapping: DxfObjectMap
) -> tuple[tuple[DrawingGroup, ...], tuple[str, ...]]:
    """Recover group members only from complete, unambiguous native handles."""
    from uuid import uuid4

    from ezdxf.document import Drawing

    drawing = cast("Drawing", document)
    groups: list[DrawingGroup] = []
    warnings: list[str] = []
    used_names: set[str] = set()
    for name, native in drawing.groups:
        members, missing = mapping.resolve_group(tuple(native.handles()))
        if missing:
            warnings.append(f"组 {name} 有 {len(missing)} 个成员无法完整或唯一恢复。")
        if not members:
            warnings.append(f"组 {name} 没有可恢复成员，已跳过。")
            continue
        group_name = None if bool(native.dxf.get("unnamed", 0)) else name
        if group_name is not None:
            unique_name = unique_import_name(group_name, used_names)
            if unique_name != group_name:
                warnings.append(f"组名称冲突：{group_name} → {unique_name}。")
            group_name = unique_name
            used_names.add(group_name.casefold())
        groups.append(
            DrawingGroup(
                uuid4().hex,
                members,
                name=group_name,
                description=str(native.dxf.get("description", "")),
                selectable=bool(native.dxf.get("selectable", 1)),
            )
        )
    return tuple(groups), tuple(warnings)
