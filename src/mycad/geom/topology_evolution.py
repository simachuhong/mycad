# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Capture one Boolean operation's native face and edge evolution.

Indices identify shapes only inside this one operation transition. They are
never persistent IDs or substitutes for semantic feature references.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from importlib import import_module
from typing import Literal, Protocol, cast

from build123d import Compound, Edge, Face, Part, Solid, Wire

from mycad.core.exceptions import GeometryBuildError
from mycad.core.topology_evolution import (
    TopologyEvolution,
    TopologyKind,
    TopologyRelation,
    TopologyTransition,
)
from mycad.geom._b123_ops import normalize_result

BooleanKind = Literal["cut", "fuse", "common"]
_Build123dShape = Compound | Part | Solid | Face | Edge | Wire


class _WrappedShape(Protocol):
    wrapped: object


def _construct(module_name: str, symbol: str, *args: object) -> object:
    constructor = cast("Callable[..., object]", getattr(import_module(module_name), symbol))
    return constructor(*args)


def _occt_call(target: object, method_name: str, *args: object) -> object:
    """Call one generated OCCT binding method through a typed Python boundary."""
    method = cast("Callable[..., object]", getattr(target, method_name))
    return method(*args)


def _is_same(first: object, second: object) -> bool:
    return cast("bool", _occt_call(first, "IsSame", second))


def _history_shapes(history: object, name: str, source: object) -> list[object]:
    successors = cast("Iterable[object]", _occt_call(history, name, source))
    return list(successors)


def _native(shape: object) -> object:
    wrapped = cast("_WrappedShape", shape).wrapped
    if wrapped is None:
        raise ValueError("Boolean operation input has no native shape")
    return wrapped


def _shape_list(shapes: Iterable[object]) -> object:
    result = _construct("OCP.TopTools", "TopTools_ListOfShape")
    for shape in shapes:
        _occt_call(result, "Append", shape)
    return result


def _unique(shapes: Iterable[object]) -> list[object]:
    result: list[object] = []
    for shape in shapes:
        if not any(_is_same(shape, existing) for existing in result):
            result.append(shape)
    return result


def _wrap(shape: object) -> Part:
    caster = cast("Callable[[object], Part]", Part.cast)
    return caster(shape)


def _entities(shape: _Build123dShape, kind: TopologyKind) -> tuple[object, ...]:
    getter = cast("Callable[[], Iterable[object]]", getattr(shape, f"{kind}s"))
    return tuple(getter())


def _unify_successors(
    source: object,
    history: object,
    final_entities: Sequence[object],
) -> tuple[int, ...]:
    changed = _unique(
        [
            *_history_shapes(history, "Modified", source),
            *_history_shapes(history, "Generated", source),
        ]
    )
    removed = cast("bool", _occt_call(history, "IsRemoved", source))
    candidates = changed if changed else ([] if removed else [source])
    return tuple(
        index
        for index, final in enumerate(final_entities)
        if any(_is_same(final, candidate) for candidate in candidates)
    )


def _evolve_kind(
    kind: TopologyKind,
    source_shapes: Sequence[_Build123dShape],
    argument_count: int,
    operation: object,
    cleanup_history: object,
    final_entities: Sequence[object],
) -> list[TopologyTransition]:
    rows: list[tuple[int, int, object, tuple[int, ...], bool, bool]] = []
    for shape_index, shape in enumerate(source_shapes):
        for source_index, entity in enumerate(_entities(shape, kind)):
            source = _native(entity)
            modified = _history_shapes(operation, "Modified", source)
            generated = _history_shapes(operation, "Generated", source)
            raw_successors = _unique([*modified, *generated])
            generated_only = bool(generated) and not modified
            deleted = cast("bool", _occt_call(operation, "IsDeleted", source))
            if not raw_successors and not deleted:
                raw_successors = [source]
            target_indices: list[int] = []
            for raw in raw_successors:
                target_indices.extend(_unify_successors(raw, cleanup_history, final_entities))
            targets = tuple(sorted(set(target_indices)))
            rows.append((shape_index, source_index, source, targets, deleted, generated_only))

    target_sources: dict[int, set[tuple[int, int]]] = {}
    for shape_index, source_index, _source, targets, _deleted, _generated in rows:
        for target in targets:
            target_sources.setdefault(target, set()).add((shape_index, source_index))

    transitions: list[TopologyTransition] = []
    for shape_index, source_index, source, targets, deleted, generated_only in rows:
        if not targets:
            relation: TopologyRelation = "deleted" if deleted else "unknown"
        elif len(targets) == 1:
            target_index = next(iter(targets))
            if len(target_sources[target_index]) > 1:
                relation = "merged"
            elif generated_only or shape_index >= argument_count:
                relation = "generated"
            elif _is_same(source, final_entities[target_index]):
                relation = "preserved"
            else:
                relation = "modified"
        else:
            relation = "split"
        transitions.append(TopologyTransition(kind, shape_index, source_index, relation, targets))
    return transitions


def boolean_with_evolution(
    operation_kind: BooleanKind,
    arguments: Sequence[_Build123dShape],
    tools: Sequence[_Build123dShape],
) -> tuple[Part | None, TopologyEvolution]:
    """Apply a Boolean operation and report source face/edge successors.

    The history covers the Boolean operation and same-domain cleanup used by
    build123d. Input-shape indices and topology indices are transient locators
    for this result only; callers must rebind semantic references after replay.
    """

    if not arguments:
        raise ValueError("Boolean operation requires at least one argument shape")
    native_arguments = [_native(shape) for shape in arguments]
    native_tools = [_native(shape) for shape in tools]
    operation_name = {
        "cut": "BRepAlgoAPI_Cut",
        "fuse": "BRepAlgoAPI_Fuse",
        "common": "BRepAlgoAPI_Common",
    }[operation_kind]
    native_operation = _construct("OCP.BRepAlgoAPI", operation_name)
    _occt_call(native_operation, "SetArguments", _shape_list(native_arguments))
    _occt_call(native_operation, "SetTools", _shape_list(native_tools))
    _occt_call(native_operation, "SetRunParallel", False)
    _occt_call(native_operation, "SetToFillHistory", True)
    _occt_call(native_operation, "Build")
    is_done = cast("bool", _occt_call(native_operation, "IsDone"))
    has_history = cast("bool", _occt_call(native_operation, "HasHistory"))
    if not is_done or not has_history:
        raise GeometryBuildError(
            f"Boolean {operation_kind} did not produce topology history",
            command_id=f"modify.boolean_{operation_kind}",
        )

    raw_result = _occt_call(native_operation, "Shape")
    final_faces: tuple[object, ...] = ()
    final_edges: tuple[object, ...] = ()
    if cast("bool", _occt_call(raw_result, "IsNull")):
        cleanup_history = _construct("OCP.BRepTools", "BRepTools_History")
        result = None
    else:
        unifier = _construct(
            "OCP.ShapeUpgrade", "ShapeUpgrade_UnifySameDomain", raw_result, True, True, True
        )
        _occt_call(unifier, "AllowInternalEdges", False)
        _occt_call(unifier, "Build")
        cleanup_history = _occt_call(unifier, "History")
        wrapped_result = _wrap(_occt_call(unifier, "Shape"))
        result = normalize_result(wrapped_result)
        final_faces = (
            () if result is None else tuple(_native(face) for face in _entities(result, "face"))
        )
        final_edges = (
            () if result is None else tuple(_native(edge) for edge in _entities(result, "edge"))
        )

    source_shapes = [*arguments, *tools]
    transitions = (
        *_evolve_kind(
            "face", source_shapes, len(arguments), native_operation, cleanup_history, final_faces
        ),
        *_evolve_kind(
            "edge", source_shapes, len(arguments), native_operation, cleanup_history, final_edges
        ),
    )
    return result, TopologyEvolution(transitions)
