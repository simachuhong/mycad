# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Bridge portable block assets to an isolated drawing collection session."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import cast
from uuid import uuid4

from mycad.core.block_library import AssetMetadata, BlockAsset, capture_block_asset
from mycad.core.block_library_import import (
    BlockPlacement,
    PreparedBlockImport,
    prepare_block_library_import,
)
from mycad.core.drawing_blocks import BlockInstance
from mycad.core.drawing_collection_state import DrawingCollectionSnapshot
from mycad.core.exceptions import ValidationError
from mycad.core.replay_proposal import ReplayAppend
from mycad.libraries.block_store import BlockLibraryStore, LibraryEntry, LibraryWriteReceipt


@dataclass(frozen=True, slots=True)
class BlockLibraryPreview:
    token: str
    checkpoint: object
    snapshot: DrawingCollectionSnapshot
    asset: BlockAsset
    prepared: PreparedBlockImport
    candidate: DrawingCollectionSnapshot


class BlockLibraryController:
    """Keep a selected asset and its document candidate frozen until confirmation."""

    def __init__(
        self,
        store: BlockLibraryStore,
        snapshot: Callable[[], DrawingCollectionSnapshot],
        checkpoint: Callable[[], object],
        stage: Callable[[ReplayAppend], object],
        preview: Callable[[ReplayAppend], DrawingCollectionSnapshot],
    ) -> None:
        self.store = store
        self._snapshot = snapshot
        self._checkpoint = checkpoint
        self._stage = stage
        self._preview = preview
        self._active_token: str | None = None

    def save_definition(
        self, definition_id: str, metadata: AssetMetadata, root_id: str, category: str
    ) -> LibraryWriteReceipt:
        """Save the current merged definition immediately without committing the draft."""
        asset = capture_block_asset(self._snapshot(), definition_id, metadata, asset_id=uuid4().hex)
        return self.store.save(root_id, category, asset, expected_digest=None)

    def prepare_import(
        self, entry: LibraryEntry, placement: BlockPlacement | None
    ) -> BlockLibraryPreview:
        """Read the selected version once and validate its isolated document candidate."""
        self._active_token = None
        checkpoint = self._checkpoint()
        snapshot = self._snapshot()
        asset = self.store.read(entry)
        prepared = prepare_block_library_import(asset, snapshot, placement=placement)
        candidate = (
            self._preview(prepared.operation) if prepared.operation is not None else snapshot
        )
        if self._checkpoint() != checkpoint or self._snapshot() != snapshot:
            raise ValidationError("图纸已变化，请重新选择块。")
        token = uuid4().hex
        self._active_token = token
        return BlockLibraryPreview(token, checkpoint, snapshot, asset, prepared, candidate)

    def reposition_preview(
        self, preview: BlockLibraryPreview, placement: BlockPlacement
    ) -> BlockLibraryPreview:
        """Validate a new transform while retaining the preview's allocated identities."""
        if preview.token != self._active_token or self._active_token is None:
            raise ValidationError("块库预览已取消或过期，请重新选择。")
        if self._checkpoint() != preview.checkpoint or self._snapshot() != preview.snapshot:
            self._active_token = None
            raise ValidationError("图纸已变化，请重新选择块。")
        operation = preview.prepared.operation
        if operation is None or preview.prepared.instance_id is None:
            raise ValidationError("仅导入定义的预览不能放置。")
        data = deepcopy(operation.params)
        operations = cast("list[dict[str, object]]", data["operations"])
        item = next(
            (child for child in operations if child["id"] == "drawing.block_instance.insert"), None
        )
        if item is None:
            raise ValidationError("块放置预览无效。")
        previous = BlockInstance.from_mapping(item["params"])
        updated = replace(
            previous,
            insertion_mm=placement.insertion_mm,
            rotation_deg=placement.rotation_deg,
            scale=placement.scale,
            layer_name=placement.layer_name,
        )
        item["params"] = updated.to_mapping()
        changed = ReplayAppend(
            operation.command_id, operation.version, data, operation.confirmed_by
        )
        candidate = self._preview(changed)
        if self._checkpoint() != preview.checkpoint or self._snapshot() != preview.snapshot:
            self._active_token = None
            raise ValidationError("图纸已变化，请重新选择块。")
        token = uuid4().hex
        self._active_token = token
        return replace(
            preview,
            token=token,
            prepared=replace(preview.prepared, operation=changed),
            candidate=candidate,
        )

    def confirm_import(self, preview: BlockLibraryPreview) -> PreparedBlockImport:
        if preview.token != self._active_token or self._active_token is None:
            raise ValidationError("块库预览已取消或过期，请重新选择。")
        if self._checkpoint() != preview.checkpoint or self._snapshot() != preview.snapshot:
            self._active_token = None
            raise ValidationError("图纸已变化，请重新选择块。")
        if preview.prepared.operation is not None:
            self._stage(preview.prepared.operation)
        self._active_token = None
        return preview.prepared

    def cancel_import(self) -> None:
        self._active_token = None
