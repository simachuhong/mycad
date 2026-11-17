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
from mycad.core.exceptions import ValidationError
from mycad.core.persistence import save_document
from mycad.ui.document_session import DocumentSession, SessionDocument
from mycad.ui.path_identity import path_identity

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
        settle: Callable[[SessionDocument, bool, Callable[[str | None], None]], None] | None = None,
    ) -> None:
        self.session = session
        self.prepare = prepare
        self.choose_path = choose_path
        self.changed = changed
        self.report = report
        self.settle = settle
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
            if on_complete is not None:
                on_complete(False)
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
        targets: list[tuple[SessionDocument, Path]] = []

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

        def settle(entry: SessionDocument, saved: bool, done: Callable[[str | None], None]) -> None:
            delivered = False

            def settled(error: str | None) -> None:
                nonlocal delivered
                if not delivered:
                    delivered = True
                    done(error)

            if self.settle is None:
                settled(None)
            else:
                try:
                    self.settle(entry, saved, settled)
                except Exception as exc:
                    if delivered:
                        raise
                    settled(str(exc))

        def failed(index: int, error: str, *, written: bool = False) -> None:
            entry = ordered[index]

            def recovered(recovery_error: str | None) -> None:
                detail = f"文件已写入，后续同步失败：{error}" if written else error
                if recovery_error:
                    detail += f"；{'界面同步' if written else '恢复'}失败：{recovery_error}"
                results.append(
                    SaveResult(
                        entry.loaded.document.document_id,
                        entry.label,
                        "saved" if written else "failed",
                        detail,
                    )
                )
                finish(False)

            settle(entry, written, recovered)

        def prepare_next(index: int) -> None:
            delivered = False

            def prepared_once(success: bool) -> None:
                nonlocal delivered
                if not delivered:
                    delivered = True
                    prepared(index, success)

            try:
                self.prepare(ordered[index], prepared_once)
            except Exception as exc:
                if delivered:
                    raise
                failed(index, str(exc))

        def prepared(index: int, success: bool) -> None:
            if not success:
                failed(index, "当前文档暂时无法保存，请等待操作完成或处理未完成的草稿。")
                return
            write_target(index)

        def saved(index: int, error: str | None) -> None:
            entry = ordered[index]
            results.append(
                SaveResult(entry.loaded.document.document_id, entry.label, "saved", error or "")
            )
            if error:
                finish(False)
            elif index + 1 < len(ordered):
                prepare_next(index + 1)
            else:
                finish(True)

        def write_target(index: int) -> None:
            seen: set[str] = set()
            for entry, path in targets:
                try:
                    if self.session.find(entry.loaded.document.document_id) is not entry:
                        raise ValidationError("待保存文档已关闭或发生变化。")
                    self.session.check_path(entry, path)
                    key = path_identity(path)
                    if key in seen:
                        raise ValidationError("多个文档不能保存到同一个目标文件。")
                    seen.add(key)
                except ValidationError as exc:
                    failed(index, str(exc))
                    return
            e, path = targets[index]
            identity = e.loaded.document.document_id
            written = False
            try:
                services, loaded = e.services, e.loaded
                if save_as and e.path is not None and path_identity(e.path) != path_identity(path):
                    services, loaded = app.copy_app_document(
                        e.services, e.loaded.document, source_bus=e.loaded.bus
                    )
                locations = dict(e.reference_locations)
                for reference in services.kernel.document_references:
                    location = locations.get(reference.file_id, reference.path)
                    source_path = Path(location) if location else None
                    if source_path is not None and not source_path.is_absolute():
                        source_path = e.path.parent / source_path if e.path is not None else None
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
                            locations[reference.file_id] = os.path.relpath(source_path, path.parent)
                        except ValueError:
                            locations[reference.file_id] = str(source_path)
                write_revision = loaded.document.revision
                save_document(
                    loaded.document,
                    path,
                    plugin_identities=app.archive_plugin_identities(services),
                    reference_locations=locations,
                )
                written = True
                if loaded.document.revision != write_revision:
                    raise ValidationError("文档在写入期间已变化，新增修改仍待保存。")
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

            except Exception as exc:
                failed(index, str(exc), written=written)
                return
            settle(e, True, lambda error: saved(index, error))

        if not ordered:
            finish(True)
            return
        seen: set[str] = set()
        for entry in ordered:
            try:
                path = self.choose_path(entry) if save_as or entry.path is None else entry.path
                if path is None:
                    results.append(
                        SaveResult(entry.loaded.document.document_id, entry.label, "cancelled")
                    )
                    finish(False)
                    return
                self.session.check_path(entry, path)
                key = path_identity(path)
                if key in seen:
                    raise ValidationError("多个文档不能保存到同一个目标文件。")
                seen.add(key)
            except ValidationError as exc:
                results.append(
                    SaveResult(entry.loaded.document.document_id, entry.label, "failed", str(exc))
                )
                finish(False)
                return
            targets.append((entry, path))
        prepare_next(0)
