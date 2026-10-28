# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Engineering sheets/views are document objects, independent of sketch geometry."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal
from uuid import UUID

from mycad.core.drawing_projection import Point2, ViewBasis, ViewDirection, finite, projected_basis
from mycad.core.drawing_references import DrawingGeometryReference

ProjectionAngle = Literal["first", "third"]
AnnotationKind = Literal[
    "horizontal", "vertical", "aligned", "radius", "diameter", "angle", "center"
]


def _identity(value: object) -> None:
    if not isinstance(value, UUID):
        raise ValueError("drawing object identity must be UUID")


def projected_offset(angle: str, direction: str, distance: float) -> Point2:
    finite((distance,), "view spacing")
    if angle not in ("first", "third") or distance <= 0:
        raise ValueError("invalid projection angle or spacing")
    sign = 1 if angle == "third" else -1
    offsets: dict[str, Point2] = {
        "top": (0, sign * distance),
        "bottom": (0, -sign * distance),
        "left": (-sign * distance, 0),
        "right": (sign * distance, 0),
    }
    if direction not in offsets:
        raise ValueError("projected layout requires a top/bottom/left/right view")
    return offsets[direction]


@dataclass(frozen=True, slots=True)
class SourceBinding:
    kind: Literal["current_part", "sketch"] = "current_part"
    sketch_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("current_part", "sketch"):
            raise ValueError("unsupported drawing source")
        if self.kind == "sketch":
            if self.sketch_id is None:
                raise ValueError("sketch source requires a sketch identity")
            parsed = UUID(self.sketch_id)
            if self.sketch_id not in (str(parsed), parsed.hex):
                raise ValueError("expected canonical sketch UUID")
        elif self.sketch_id is not None:
            raise ValueError("part source cannot carry a sketch identity")


@dataclass(frozen=True, slots=True)
class DrawingSheet:
    sheet_id: UUID
    name: str = "工程图1"
    size_mm: Point2 = (297, 210)
    margin_mm: float = 10
    projection_angle: ProjectionAngle = "first"
    default_scale: float = 1
    title: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        _identity(self.sheet_id)
        finite((*self.size_mm, self.margin_mm, self.default_scale), "sheet")
        if min(self.size_mm) <= 0 or not 0 <= self.margin_mm < min(self.size_mm) / 2:
            raise ValueError("invalid sheet size or margin")
        if self.default_scale <= 0 or self.projection_angle not in ("first", "third"):
            raise ValueError("invalid default scale or projection angle")
        if not self.name.strip() or len({key for key, _ in self.title}) != len(self.title):
            raise ValueError("sheet name/title invalid")

    @classmethod
    def for_paper(cls, sheet_id: UUID, paper: str, *, landscape: bool = True) -> DrawingSheet:
        if paper not in ("A4", "A3"):
            raise ValueError("supported paper sizes are A4/A3")
        width, height = (210, 297) if paper == "A4" else (297, 420)
        return cls(sheet_id, size_mm=(height, width) if landscape else (width, height))


@dataclass(frozen=True, slots=True)
class DrawingView:
    view_id: UUID
    sheet_id: UUID
    source: SourceBinding = SourceBinding()
    basis: ViewBasis = ViewBasis()
    parent_id: UUID | None = None
    direction: ViewDirection = "front"
    anchor_mm: Point2 = (0, 0)
    offset_mm: Point2 = (0, 0)
    scale: float = 1
    inherit_scale: bool = True
    aligned: bool = True
    hidden_lines: bool = True
    tangent_lines: bool = False
    inherit_display: bool = True

    def __post_init__(self) -> None:
        _identity(self.view_id)
        _identity(self.sheet_id)
        if self.parent_id is not None:
            _identity(self.parent_id)
        if self.source.kind == "sketch" and (
            self.parent_id is not None or self.direction != "front"
        ):
            raise ValueError("sketch views are independent planar views")
        finite((*self.anchor_mm, *self.offset_mm), "view position")
        finite((self.scale,), "view scale")
        if self.scale <= 0:
            raise ValueError("view scale must be positive")
        if self.direction not in ("front", "back", "top", "bottom", "left", "right"):
            raise ValueError("invalid view direction")


@dataclass(frozen=True, slots=True)
class DrawingAnnotation:
    annotation_id: UUID
    view_id: UUID
    kind: AnnotationKind
    references: tuple[DrawingGeometryReference, ...]
    position_mm: Point2
    precision: int = 2
    layer: str = "DIM"
    prefix: str = ""
    suffix: str = " mm"

    def __post_init__(self) -> None:
        _identity(self.annotation_id)
        _identity(self.view_id)
        finite(self.position_mm, "annotation position")
        if self.kind not in (
            "horizontal",
            "vertical",
            "aligned",
            "radius",
            "diameter",
            "angle",
            "center",
        ):
            raise ValueError("unsupported drawing annotation kind")
        if not self.references or not 0 <= self.precision <= 8 or not self.layer.strip():
            raise ValueError("invalid annotation references/precision/layer")


@dataclass(frozen=True, slots=True)
class DrawingState:
    sheets: tuple[DrawingSheet, ...] = ()
    views: tuple[DrawingView, ...] = ()
    annotations: tuple[DrawingAnnotation, ...] = ()

    def __post_init__(self) -> None:
        sheet_ids = [sheet.sheet_id for sheet in self.sheets]
        view_ids = [view.view_id for view in self.views]
        annotation_ids = [annotation.annotation_id for annotation in self.annotations]
        ids = [*sheet_ids, *view_ids, *annotation_ids]
        if len(set(ids)) != len(ids):
            raise ValueError("drawing object identities must be unique")
        for view in self.views:
            if view.sheet_id not in sheet_ids:
                raise ValueError("view references a missing sheet")
            visited = {view.view_id}
            current = view
            while current.parent_id is not None:
                if current.parent_id in visited:
                    raise ValueError("view parent cycle")
                visited.add(current.parent_id)
                current = self.view(current.parent_id)
                if current.source != view.source or current.source.kind == "sketch":
                    raise ValueError("projected views require the same solid source")
                if current.sheet_id != view.sheet_id:
                    raise ValueError("parent must belong to same sheet")
        if any(a.view_id not in view_ids for a in self.annotations):
            raise ValueError("annotation references a missing view")

    def sheet(self, identity: UUID) -> DrawingSheet:
        for sheet in self.sheets:
            if sheet.sheet_id == identity:
                return sheet
        raise ValueError(f"missing sheet {identity}")

    def view(self, identity: UUID) -> DrawingView:
        for view in self.views:
            if view.view_id == identity:
                return view
        raise ValueError(f"missing view {identity}")

    def effective_basis(self, identity: UUID) -> ViewBasis:
        view = self.view(identity)
        if view.parent_id is not None:
            return projected_basis(self.effective_basis(view.parent_id), view.direction)
        return view.basis

    def effective_scale(self, identity: UUID) -> float:
        view = self.view(identity)
        if view.parent_id is not None and view.inherit_scale:
            return self.effective_scale(view.parent_id)
        return view.scale

    def effective_anchor(self, identity: UUID) -> Point2:
        view = self.view(identity)
        if view.parent_id is None or not view.aligned:
            return view.anchor_mm
        x, y = self.effective_anchor(view.parent_id)
        if view.direction in ("top", "bottom"):
            return (x, y + view.offset_mm[1])
        if view.direction in ("left", "right"):
            return (x + view.offset_mm[0], y)
        return (x + view.offset_mm[0], y + view.offset_mm[1])

    def effective_display(self, identity: UUID) -> tuple[bool, bool]:
        view = self.view(identity)
        if view.parent_id is not None and view.inherit_display:
            return self.effective_display(view.parent_id)
        return (view.hidden_lines, view.tangent_lines)


@dataclass(frozen=True, slots=True)
class DrawingOperation:
    action: Literal["create", "update", "delete"]
    kind: Literal["sheet", "view", "annotation"]
    object_id: UUID
    value: DrawingSheet | DrawingView | DrawingAnnotation | None = None


def apply_drawing_operation(state: DrawingState, operation: DrawingOperation) -> DrawingState:
    """Return validated replacement state; failure never mutates the input."""
    _identity(operation.object_id)
    if operation.action not in ("create", "update", "delete"):
        raise ValueError("invalid drawing operation")
    if operation.kind not in ("sheet", "view", "annotation"):
        raise ValueError("invalid drawing object kind")
    sheets = {s.sheet_id: s for s in state.sheets}
    views = {v.view_id: v for v in state.views}
    annotations = {a.annotation_id: a for a in state.annotations}
    identity = operation.object_id
    value = operation.value
    existing = (
        identity in {"sheet": sheets, "view": views, "annotation": annotations}[operation.kind]
    )
    if operation.action == "create" and existing:
        raise ValueError("drawing object already exists")
    if operation.action != "create" and not existing:
        raise ValueError("drawing object does not exist")
    if operation.action == "delete":
        if value is not None:
            raise ValueError("delete cannot carry replacement object")
        if operation.kind == "sheet":
            del sheets[identity]
        removed = {
            v.view_id
            for v in views.values()
            if v.sheet_id not in sheets or (operation.kind == "view" and v.view_id == identity)
        }
        while True:
            children = {v.view_id for v in views.values() if v.parent_id in removed}
            if children <= removed:
                break
            removed |= children
        views = {key: view for key, view in views.items() if key not in removed}
        annotations = {
            key: a
            for key, a in annotations.items()
            if a.view_id in views and not (operation.kind == "annotation" and key == identity)
        }
    elif (
        operation.kind == "sheet" and isinstance(value, DrawingSheet) and value.sheet_id == identity
    ):
        sheets[identity] = value
    elif operation.kind == "view" and isinstance(value, DrawingView) and value.view_id == identity:
        views[identity] = value
    elif (
        operation.kind == "annotation"
        and isinstance(value, DrawingAnnotation)
        and value.annotation_id == identity
    ):
        annotations[identity] = value
    else:
        raise ValueError("operation value kind/identity mismatch")
    return replace(
        state,
        sheets=tuple(sheets.values()),
        views=tuple(views.values()),
        annotations=tuple(annotations.values()),
    )
