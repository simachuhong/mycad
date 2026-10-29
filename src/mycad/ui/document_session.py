# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Editable documents own their services and paths; workspaces only select them."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from mycad.core.document_kinds import DocumentKind
from mycad.core.exceptions import ValidationError

if TYPE_CHECKING:
    from mycad.app import AppServices
    from mycad.core.persistence import LoadedDocument
    from mycad.ui.drawing_workbench import DrawingWorkbench
    from mycad.ui.plan_draft import PlanDraftController
    from mycad.ui.sketch_editor import SketchEditorDialog
    from mycad.ui.viewport import ViewportViewState

KIND_LABELS: dict[DocumentKind, str] = {
    "sketch": "平面草图",
    "drawing": "工程图",
    "part": "三维零件",
}
DEFAULT_NAMES: dict[DocumentKind, str] = {
    "sketch": "untitled-sketch.my2d",
    "drawing": "untitled-drawing.my2d",
    "part": "untitled.my3d",
}


@dataclass(eq=False)
class SessionDocument:
    services: AppServices
    loaded: LoadedDocument
    path: Path | None = None
    placeholder: bool = False
    draft: SketchEditorDialog | None = None
    workbench: DrawingWorkbench | None = None
    view_state: ViewportViewState | None = None
    plan_draft: PlanDraftController | None = None
    reference_locations: dict[str, str] = field(default_factory=dict)
    reference_messages: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        self.reference_locations = self.loaded.document.reference_locations

    @property
    def kind(self) -> DocumentKind:
        return self.loaded.document.document_kind

    @property
    def label(self) -> str:
        return f"{self.path.name if self.path else DEFAULT_NAMES[self.kind]} · {KIND_LABELS[self.kind]}"

    @property
    def has_draft(self) -> bool:
        return self.draft is not None and bool(
            self.draft.canvas.entities or self.draft.canvas.has_pending_geometry
        )

    @property
    def needs_save(self) -> bool:
        bench = self.workbench
        pending = bench is not None and (
            bench.notes.pending
            or bench.annotations.pending
            or (bench.placement is not None and bench.placement.pending)
        )
        return bool(
            self.loaded.document.is_dirty
            or self.has_draft
            or pending
            or (self.path is None and not self.placeholder)
        )


class DocumentSession:
    def __init__(self) -> None:
        self._documents: dict[str, SessionDocument] = {}
        self.active: SessionDocument | None = None
        self._last_kind: dict[DocumentKind, str] = {}

    @property
    def documents(self) -> tuple[SessionDocument, ...]:
        return tuple(self._documents.values())

    def add(self, document: SessionDocument) -> None:
        identity = document.loaded.document.document_id
        if document.path is not None:
            self.check_path(document, document.path)
        if any(
            d is not document and d.loaded.document.file_id == document.loaded.document.file_id
            for d in self.documents
        ):
            raise ValidationError(
                "This file identity is already open; activate the existing document."
            )
        self._documents[identity] = document

    def activate(self, identity: str) -> SessionDocument:
        document = self._documents[identity]
        self.active = document
        self._last_kind[document.kind] = identity
        return document

    def latest(self, kind: DocumentKind) -> SessionDocument | None:
        identity = self._last_kind.get(kind)
        return self._documents.get(identity) if identity is not None else None

    def find(self, identity: str) -> SessionDocument | None:
        return self._documents.get(identity)

    def remove(self, identity: str) -> None:
        document = self._documents.pop(identity)
        if self.active is document:
            self.active = None
        if self._last_kind.get(document.kind) == identity:
            self._last_kind.pop(document.kind, None)

    def check_path(self, document: SessionDocument, path: Path) -> None:
        import os

        normalized = os.path.normcase(str(path.resolve()))
        if any(
            d is not document
            and d.path is not None
            and os.path.normcase(str(d.path.resolve())) == normalized
            for d in self.documents
        ):
            raise ValidationError("目标文件已由另一个打开的文档使用，请选择不同的路径。")
