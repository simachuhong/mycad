# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""A block library persists assets without silently overwriting concurrent changes."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from mycad.core.block_library import BlockAsset
from mycad.core.drawing_blocks import BlockDefinition
from mycad.core.drawing_text import TextStyleTable
from mycad.core.sketch import LineEntity
from mycad.core.sketch_layers import SketchLayerTable
from mycad.libraries.block_store import BlockLibraryStore, LibraryRoot

_ATOMIC_WRITE_NAME = "_atomic_write"


def make_asset() -> BlockAsset:
    definition = BlockDefinition(uuid4().hex, "块", (LineEntity(uuid4().hex, (0, 0), (1, 2)),), ())
    return BlockAsset(uuid4().hex, "块", "", (), definition, TextStyleTable(), SketchLayerTable())


def test_local_update_detects_conflict_and_preserves_restore(tmp_path: Path) -> None:
    root = LibraryRoot("local", tmp_path / "local", False)
    store = BlockLibraryStore((root,), tmp_path / "cache")
    asset = make_asset()
    first = store.save("local", "部件", asset, expected_digest=None)
    entry = store.scan("local").entries[0]
    assert store.read(entry) == asset
    second = store.save(
        "local", "部件", replace(asset, description="v2"), expected_digest=first.file_digest
    )
    with pytest.raises(ValueError, match="变化"):
        store.save("local", "部件", asset, expected_digest=first.file_digest)
    assert store.read(store.scan("local").entries[0]).description == "v2"
    store.restore(second)
    assert store.read(store.scan("local").entries[0]) == asset


def test_shared_readonly_offline_and_bad_entry(tmp_path: Path) -> None:
    source = tmp_path / "shared"
    source.mkdir()
    asset = make_asset()
    local = BlockLibraryStore((LibraryRoot("local", source, False),), tmp_path / "cache")
    local.save("local", "", asset, expected_digest=None)
    (source / "bad.myblock").write_bytes(b"not json")
    store = BlockLibraryStore((LibraryRoot("shared", source, True),), tmp_path / "cache")
    scan = store.scan("shared")
    assert len(scan.entries) == 1 and len(scan.issues) == 1
    assert store.read(scan.entries[0]) == asset
    with pytest.raises(ValueError, match="只读"):
        store.save("shared", "", asset, expected_digest=None)
    unavailable = BlockLibraryStore(
        (LibraryRoot("s", tmp_path / "missing", True),), tmp_path / "cache"
    )
    assert unavailable.scan("s").issues


def test_trash_restore_refuses_occupied_path(tmp_path: Path) -> None:
    store = BlockLibraryStore(
        (LibraryRoot("local", tmp_path / "local", False),), tmp_path / "cache"
    )
    asset = make_asset()
    store.save("local", "", asset, expected_digest=None)
    receipt = store.trash(store.scan("local").entries[0])
    store.save("local", "", asset, expected_digest=None)
    with pytest.raises(ValueError, match="变化|占用"):
        store.restore(receipt)
    assert len(store.scan("local").entries) == 1


def test_same_category_names_are_made_unique(tmp_path: Path) -> None:
    store = BlockLibraryStore((LibraryRoot("local", tmp_path / "lib", False),), tmp_path / "cache")
    first, second = make_asset(), make_asset()
    store.save("local", "", first, expected_digest=None)
    store.save("local", "", second, expected_digest=None)
    assert {entry.asset.name for entry in store.scan("local").entries} == {"块", "块 副本"}


def test_restore_wont_overwrite_later_update(tmp_path: Path) -> None:
    store = BlockLibraryStore((LibraryRoot("local", tmp_path / "lib", False),), tmp_path / "cache")
    asset = make_asset()
    v1 = store.save("local", "", asset, expected_digest=None)
    v2 = store.save("local", "", replace(asset, description="v2"), expected_digest=v1.file_digest)
    store.save("local", "", replace(asset, description="v3"), expected_digest=v2.file_digest)
    with pytest.raises(ValueError, match="变化"):
        store.restore(v2)
    assert store.read(store.scan("local").entries[0]).description == "v3"


def test_write_failure_keeps_original_and_cleans_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import mycad.libraries.block_store as module

    store = BlockLibraryStore((LibraryRoot("local", tmp_path / "lib", False),), tmp_path / "cache")
    asset = make_asset()
    first = store.save("local", "", asset, expected_digest=None)
    original_replace = module.os.replace

    def fail_target(source: str | Path, target: str | Path) -> None:
        if Path(target).name == f"{asset.asset_id}.myblock":
            raise OSError("disk failure")
        original_replace(source, target)

    monkeypatch.setattr(module.os, "replace", fail_target)
    with pytest.raises(OSError, match="disk failure"):
        store.save("local", "", replace(asset, description="v2"), expected_digest=first.file_digest)
    assert store.read(store.scan("local").entries[0]) == asset
    assert not list((tmp_path / "lib").rglob(".myblock-*"))


def test_internal_folders_cannot_be_user_categories(tmp_path: Path) -> None:
    store = BlockLibraryStore((LibraryRoot("local", tmp_path / "lib", False),), tmp_path / "cache")
    with pytest.raises(ValueError):
        store.save("local", ".history", make_asset(), expected_digest=None)


def _concurrent_writer(root: Path, asset: BlockAsset, expected: str, queue: object) -> None:
    from multiprocessing.queues import Queue
    from typing import cast

    result = cast("Queue[str]", queue)
    store = BlockLibraryStore((LibraryRoot("local", root, False),), root / "cache")
    try:
        store.save("local", "", asset, expected_digest=expected)
        result.put("ok")
    except ValueError:
        result.put("conflict")


def test_concurrent_updates_and_stale_entry(tmp_path: Path) -> None:
    import multiprocessing

    root = tmp_path / "library"
    store = BlockLibraryStore((LibraryRoot("local", root, False),), tmp_path / "cache")
    asset = make_asset()
    first = store.save("local", "", asset, expected_digest=None)
    entry = store.scan("local").entries[0]
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    workers = [
        ctx.Process(
            target=_concurrent_writer,
            args=(root, replace(asset, description=f"update {i}"), first.file_digest, queue),
        )
        for i in range(2)
    ]
    for worker in workers:
        worker.start()
    results = [queue.get(timeout=20) for _ in workers]
    for worker in workers:
        worker.join(timeout=20)
        assert worker.exitcode == 0
    assert sorted(results) == ["conflict", "ok"]
    with pytest.raises(ValueError, match="变化"):
        store.read(entry)
    queue.close()


def test_scan_skips_symbolic_link_cycles(tmp_path: Path) -> None:
    root = tmp_path / "library"
    store = BlockLibraryStore((LibraryRoot("local", root, False),), tmp_path / "cache")
    store.save("local", "", make_asset(), expected_digest=None)
    (root / "loop").symlink_to(root, target_is_directory=True)
    assert len(store.scan("local").entries) == 1
    with pytest.raises(ValueError, match="路径"):
        store.save("local", "loop", make_asset(), expected_digest=None)


def test_rename_rejects_existing_name_and_reports_symlink(tmp_path: Path) -> None:
    root = tmp_path / "library"
    store = BlockLibraryStore((LibraryRoot("local", root, False),), tmp_path / "cache")
    first, second = make_asset(), make_asset()
    store.save("local", "", first, expected_digest=None)
    saved = store.save("local", "", second, expected_digest=None)
    renamed = replace(second, name="块", definition=replace(second.definition, name="块"))
    with pytest.raises(ValueError, match="名称"):
        store.save("local", "", renamed, expected_digest=saved.file_digest)
    (root / "loop").symlink_to(root, target_is_directory=True)
    assert any("loop" in issue.path for issue in store.scan("local").issues)


def test_recovery_receipts_survive_store_recreation(tmp_path: Path) -> None:
    root = LibraryRoot("local", tmp_path / "library", False)
    store = BlockLibraryStore((root,), tmp_path / "cache")
    asset = make_asset()
    first = store.save("local", "category", asset, expected_digest=None)
    second = store.save(
        "local", "category", replace(asset, description="v2"), expected_digest=first.file_digest
    )
    trashed = store.trash(store.scan("local").entries[0])
    reopened = BlockLibraryStore((root,), tmp_path / "cache")
    receipts = reopened.list_recovery("local")
    assert second in receipts and trashed in receipts
    reopened.restore(trashed)
    reopened.restore(second)
    assert reopened.read(reopened.scan("local").entries[0]) == asset
    assert not reopened.list_recovery("local")


def test_failed_post_replace_sync_retains_previous_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import mycad.libraries.block_store as module

    root = LibraryRoot("local", tmp_path / "library", False)
    store = BlockLibraryStore((root,), tmp_path / "cache")
    asset = make_asset()
    first = store.save("local", "", asset, expected_digest=None)
    from collections.abc import Callable
    from typing import cast

    atomic_write = cast("Callable[[Path, bytes], None]", vars(module)[_ATOMIC_WRITE_NAME])

    def fail_after_replacement(path: Path, data: bytes) -> None:
        atomic_write(path, data)
        if path == root.path / f"{asset.asset_id}.myblock":
            raise OSError("directory sync failed")

    monkeypatch.setattr(module, _ATOMIC_WRITE_NAME, fail_after_replacement)
    with pytest.raises(OSError, match="sync"):
        store.save("local", "", replace(asset, description="v2"), expected_digest=first.file_digest)
    receipts = store.list_recovery("local")
    assert len(receipts) == 1
    monkeypatch.setattr(module, _ATOMIC_WRITE_NAME, atomic_write)
    store.restore(receipts[0])
    assert store.read(store.scan("local").entries[0]) == asset
