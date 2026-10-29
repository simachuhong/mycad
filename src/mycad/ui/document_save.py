# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Per-document save transactions and dependency-ordered multi-file results."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from mycad import app
from mycad.core.document_dependencies import save_order
from mycad.core.exceptions import MycadError, ValidationError
from mycad.core.persistence import save_document
from mycad.ui.document_session import DocumentSession, SessionDocument

SaveStatus = Literal["saved", "cancelled", "failed", "pending"]


@dataclass(frozen=True)
class SaveResult:
    document_id: str
    label: str
    status: SaveStatus
    error: str = ""


class DocumentSaveController:
    def __init__(
        self,
        session: DocumentSession,
        *,
        prepare: Callable[[SessionDocument, Callable[[bool], None]], None],
        choose_path: Callable[[SessionDocument], Path | None],
        changed: Callable[[], None],
        report: Callable[[tuple[SaveResult, ...]], None],
    ) -> None:
        self.session = session
        self.prepare = prepare
        self.choose_path = choose_path
        self.changed = changed
        self.report = report
        self.running = False
        self.last_results: tuple[SaveResult, ...] = ()

    def save_one(self, entry: SessionDocument, *, save_as: bool = False) -> None:
        self.save_many((entry,), save_as=save_as)

    def save_many(
        self,
        entries: Sequence[SessionDocument],
        *,
        save_as: bool = False,
        on_complete: Callable[[bool], None] | None = None,
    ) -> None:
        if self.running:
            return
        self.running = True
        by_id = {e.loaded.document.file_id: e for e in entries}
        nodes = {
            key: tuple(r.file_id for r in e.services.kernel.document_references)
            for key, e in by_id.items()
        }
        try:
            ordered = tuple(by_id[key] for key in save_order(nodes))
        except ValidationError as exc:
            self.running = False
            self.last_results = (SaveResult("", "文档依赖", "failed", str(exc)),)
            self.report(self.last_results)
            if on_complete is not None:
                on_complete(False)
            return
        results: list[SaveResult] = []

        def finish(success: bool) -> None:
            self.running = False
            finished = {r.document_id for r in results}
            results.extend(
                SaveResult(e.loaded.document.document_id, e.label, "pending")
                for e in ordered
                if e.loaded.document.document_id not in finished
            )
            self.last_results = tuple(results)
            self.changed()
            self.report(self.last_results)
            if on_complete is not None:
                on_complete(success)

        def prepared(index: int, success: bool) -> None:
            if not success:
                e = ordered[index]
                results.append(
                    SaveResult(
                        e.loaded.document.document_id,
                        e.label,
                        "failed",
                        "当前草稿尚未完成或提交失败，内容已保留。",
                    )
                )
                finish(False)
            elif index + 1 < len(ordered):
                self.prepare(ordered[index + 1], lambda ok: prepared(index + 1, ok))
            else:
                collect_and_write()

        def collect_and_write() -> None:
            targets: list[tuple[SessionDocument, Path]] = []
            seen: set[str] = set()
            for e in ordered:
                path = self.choose_path(e) if save_as or e.path is None else e.path
                if path is None:
                    results.append(SaveResult(e.loaded.document.document_id, e.label, "cancelled"))
                    finish(False)
                    return
                try:
                    self.session.check_path(e, path)
                    key = os.path.normcase(str(path.resolve()))
                    if key in seen:
                        raise ValidationError("多个文档不能保存到同一个目标文件。")
                    seen.add(key)
                except ValidationError as exc:
                    results.append(
                        SaveResult(e.loaded.document.document_id, e.label, "failed", str(exc))
                    )
                    finish(False)
                    return
                targets.append((e, path))
            for e, path in targets:
                identity, label = e.loaded.document.document_id, e.label
                try:
                    services, loaded = e.services, e.loaded
                    if (
                        save_as
                        and e.path is not None
                        and os.path.normcase(str(e.path.resolve()))
                        != os.path.normcase(str(path.resolve()))
                    ):
                        services, loaded = app.copy_app_document(e.services, e.loaded.document)
                    locations = dict(e.reference_locations)
                    for reference in services.kernel.document_references:
                        location = locations.get(reference.file_id, reference.path)
                        source_path = Path(location) if location else None
                        if source_path is not None and not source_path.is_absolute():
                            source_path = (
                                e.path.parent / source_path if e.path is not None else None
                            )
                        source = next(
                            (
                                d
                                for d in self.session.documents
                                if d.loaded.document.file_id == reference.file_id
                            ),
                            None,
                        )
                        if source is not None and source.path is not None:
                            source_path = source.path
                        if source_path is not None:
                            try:
                                locations[reference.file_id] = os.path.relpath(
                                    source_path, path.parent
                                )
                            except ValueError:
                                locations[reference.file_id] = str(source_path)
                    save_document(
                        loaded.document,
                        path,
                        plugin_identities=app.archive_plugin_identities(services),
                        reference_locations=locations,
                    )
                    loaded.document.mark_clean()
                    if loaded is not e.loaded:
                        active = self.session.active is e
                        self.session.remove(identity)
                        e.services, e.loaded = services, loaded
                        if e.workbench is not None:
                            e.workbench.shutdown()
                        e.draft, e.workbench = None, None
                        e.plan_draft = None
                        self.session.add(e)
                        if active:
                            self.session.activate(e.loaded.document.document_id)
                    e.path = path
                    e.reference_locations = locations
                    e.placeholder = False
                    results.append(SaveResult(e.loaded.document.document_id, label, "saved"))
                except (OSError, MycadError) as exc:
                    results.append(SaveResult(identity, label, "failed", str(exc)))
                    finish(False)
                    return
            finish(True)

        if not ordered:
            finish(True)
        else:
            self.prepare(ordered[0], lambda ok: prepared(0, ok))
