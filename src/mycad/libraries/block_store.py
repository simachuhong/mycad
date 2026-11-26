# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Filesystem-backed block libraries with conflict-checked local writes."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Generator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast
from uuid import uuid4

from mycad.core.block_library import BlockAsset
from mycad.formats.block_asset import MAX_FILE_BYTES, decode_block_asset, encode_block_asset


@dataclass(frozen=True, slots=True)
class LibraryRoot:
    root_id: str
    path: Path
    read_only: bool


@dataclass(frozen=True, slots=True)
class LibraryIssue:
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class LibraryEntry:
    root_id: str
    relative_path: str
    file_digest: str
    asset: BlockAsset


@dataclass(frozen=True, slots=True)
class LibraryScan:
    entries: tuple[LibraryEntry, ...]
    issues: tuple[LibraryIssue, ...]


@dataclass(frozen=True, slots=True)
class LibraryWriteReceipt:
    root_id: str
    relative_path: str
    file_digest: str | None
    previous_version_path: str | None


def _receipt_bytes(receipt: LibraryWriteReceipt) -> bytes:
    return json.dumps(
        {
            "version": 1,
            "root_id": receipt.root_id,
            "relative_path": receipt.relative_path,
            "file_digest": receipt.file_digest,
            "previous_version_path": receipt.previous_version_path,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _metadata_path(root: Path, backup: str) -> Path:
    return _contained(root, backup + ".json")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_bytes(path: Path) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("块文件超过大小限制。")
    return data


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".myblock-", delete=False) as f:
            temporary = Path(f.name)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
        temporary = None
        if os.name != "nt":
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def _locked(root: Path) -> Generator[None, None, None]:
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".block-library.lock").open("a+b") as lock:
        if os.name == "nt":
            import msvcrt

            lock.seek(0)
            if lock.read(1) == b"":
                lock.write(b"\0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _contained(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or any(part in ("..", ".") for part in path.parts):
        raise ValueError("块库路径无效。")
    target = root / path
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("块库路径超出目录。")
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("块库路径不能使用符号链接。")
    return target


class BlockLibraryStore:
    def __init__(self, roots: tuple[LibraryRoot, ...], cache_dir: Path) -> None:
        if len({root.root_id for root in roots}) != len(roots):
            raise ValueError("块库身份重复。")
        self._roots = {root.root_id: root for root in roots}
        self.cache_dir = cache_dir

    def _root(self, root_id: str, *, writable: bool = False) -> LibraryRoot:
        try:
            root = self._roots[root_id]
        except KeyError as exc:
            raise ValueError("块库不存在。") from exc
        if writable and root.read_only:
            raise ValueError("该块库为只读目录。")
        return root

    def scan(self, root_id: str) -> LibraryScan:
        root = self._root(root_id)
        entries: list[LibraryEntry] = []
        issues: list[LibraryIssue] = []
        if not root.path.is_dir():
            return LibraryScan((), (LibraryIssue(str(root.path), "块库目录不可用。"),))

        def error(exc: OSError) -> None:
            issues.append(LibraryIssue(str(exc.filename or root.path), str(exc)))

        for folder, directories, files in os.walk(root.path, followlinks=False, onerror=error):
            base = Path(folder)
            for name in directories:
                if (base / name).is_symlink():
                    issues.append(
                        LibraryIssue(
                            (base / name).relative_to(root.path).as_posix(), "跳过符号链接目录。"
                        )
                    )
            directories[:] = sorted(
                name
                for name in directories
                if name not in {".history", ".trash"} and not (base / name).is_symlink()
            )
            for name in sorted(files):
                path = base / name
                if path.suffix.lower() != ".myblock":
                    continue
                relative = path.relative_to(root.path).as_posix()
                if path.is_symlink():
                    issues.append(LibraryIssue(relative, "跳过符号链接文件。"))
                    continue
                try:
                    data = _read_bytes(path)
                    entries.append(
                        LibraryEntry(root_id, relative, _digest(data), decode_block_asset(data))
                    )
                except (OSError, ValueError) as exc:
                    issues.append(LibraryIssue(relative, str(exc)))
        return LibraryScan(tuple(entries), tuple(issues))

    def read(self, entry: LibraryEntry) -> BlockAsset:
        root = self._root(entry.root_id)
        data = _read_bytes(_contained(root.path, entry.relative_path))
        if _digest(data) != entry.file_digest:
            raise ValueError("块文件已变化，请刷新。")
        return decode_block_asset(data)

    def save(
        self, root_id: str, category: str, asset: BlockAsset, *, expected_digest: str | None
    ) -> LibraryWriteReceipt:
        root = self._root(root_id, writable=True)
        if any(part.startswith(".") for part in Path(category).parts):
            raise ValueError("不能使用隐藏目录作为块分类。")
        relative = (Path(category) / f"{asset.asset_id}.myblock").as_posix()
        target = _contained(root.path, relative)
        with _locked(root.path):
            target = _contained(root.path, relative)
            old = _read_bytes(target) if target.exists() else None
            if (None if old is None else _digest(old)) != expected_digest:
                raise ValueError("块文件已变化或名称已被占用，请刷新。")
            names: set[str] = set()
            if target.parent.is_dir():
                for existing in target.parent.iterdir():
                    if (
                        existing == target
                        or existing.suffix.lower() != ".myblock"
                        or existing.is_symlink()
                    ):
                        continue
                    try:
                        names.add(decode_block_asset(_read_bytes(existing)).name.casefold())
                    except (OSError, ValueError):
                        continue
            if old is not None and asset.name.casefold() in names:
                raise ValueError("同一分类已有相同块名称。")
            if old is None:
                name = asset.name
                suffix = 1
                while name.casefold() in names:
                    name = f"{asset.name} 副本" if suffix == 1 else f"{asset.name} 副本 {suffix}"
                    suffix += 1
                if name != asset.name:
                    asset = replace(
                        asset, name=name, definition=replace(asset.definition, name=name)
                    )
            data = encode_block_asset(asset)
            decode_block_asset(data)
            backup: str | None = None
            receipt = LibraryWriteReceipt(root_id, relative, _digest(data), None)
            if old is not None:
                backup = f".history/{asset.asset_id}-{uuid4().hex}.myblock"
                receipt = LibraryWriteReceipt(root_id, relative, _digest(data), backup)
                try:
                    _atomic_write(_contained(root.path, backup), old)
                    _atomic_write(_metadata_path(root.path, backup), _receipt_bytes(receipt))
                except OSError:
                    _contained(root.path, backup).unlink(missing_ok=True)
                    _metadata_path(root.path, backup).unlink(missing_ok=True)
                    raise
            try:
                _atomic_write(target, data)
            except OSError:
                # Replacement may have succeeded before directory fsync failed.
                # Delete recovery data only when the original bytes are still present.
                unchanged = False
                if old is not None:
                    with suppress(OSError):
                        unchanged = _read_bytes(target) == old
                if backup is not None and unchanged:
                    _contained(root.path, backup).unlink(missing_ok=True)
                    _metadata_path(root.path, backup).unlink(missing_ok=True)
                raise
            return receipt

    def trash(self, entry: LibraryEntry) -> LibraryWriteReceipt:
        root = self._root(entry.root_id, writable=True)
        with _locked(root.path):
            target = _contained(root.path, entry.relative_path)
            if not target.exists() or _digest(_read_bytes(target)) != entry.file_digest:
                raise ValueError("块文件已变化，请刷新。")
            backup = f".trash/{entry.asset.asset_id}-{uuid4().hex}.myblock"
            destination = _contained(root.path, backup)
            destination.parent.mkdir(parents=True, exist_ok=True)
            receipt = LibraryWriteReceipt(entry.root_id, entry.relative_path, None, backup)
            _atomic_write(_metadata_path(root.path, backup), _receipt_bytes(receipt))
            try:
                os.replace(target, destination)
            except OSError:
                _metadata_path(root.path, backup).unlink(missing_ok=True)
                raise
            return receipt

    def restore(self, receipt: LibraryWriteReceipt) -> LibraryWriteReceipt:
        root = self._root(receipt.root_id, writable=True)
        if receipt.previous_version_path is None:
            raise ValueError("没有可恢复的版本。")
        with _locked(root.path):
            target = _contained(root.path, receipt.relative_path)
            backup = _contained(root.path, receipt.previous_version_path)
            current = _read_bytes(target) if target.exists() else None
            if (None if current is None else _digest(current)) != receipt.file_digest:
                raise ValueError("块文件已变化或目标路径已占用。")
            restored = _read_bytes(backup)
            decode_block_asset(restored)
            _atomic_write(target, restored)
            backup.unlink()
            _metadata_path(root.path, receipt.previous_version_path).unlink(missing_ok=True)
            return LibraryWriteReceipt(
                receipt.root_id, receipt.relative_path, _digest(restored), None
            )

    def list_recovery(self, root_id: str) -> tuple[LibraryWriteReceipt, ...]:
        """Find persisted recovery receipts without trusting paths from disk."""
        root = self._root(root_id, writable=True)
        found: list[LibraryWriteReceipt] = []
        for folder in (".history", ".trash"):
            directory = _contained(root.path, folder)
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.myblock.json")):
                try:
                    if path.is_symlink() or path.stat().st_size > 8192:
                        continue
                    raw: object = json.loads(path.read_text(encoding="utf-8"))
                    if not isinstance(raw, dict):
                        continue
                    value = cast("dict[str, object]", raw)
                    if (
                        set(value)
                        != {
                            "version",
                            "root_id",
                            "relative_path",
                            "file_digest",
                            "previous_version_path",
                        }
                        or value["version"] != 1
                        or value["root_id"] != root_id
                    ):
                        continue
                    relative, digest, previous = (
                        value["relative_path"],
                        value["file_digest"],
                        value["previous_version_path"],
                    )
                    if (
                        not isinstance(relative, str)
                        or not isinstance(previous, str)
                        or not (digest is None or isinstance(digest, str))
                    ):
                        continue
                    if (
                        _metadata_path(root.path, previous) != path
                        or not _contained(root.path, previous).is_file()
                    ):
                        continue
                    _contained(root.path, relative)
                    found.append(LibraryWriteReceipt(root_id, relative, digest, previous))
                except (OSError, UnicodeError, ValueError, TypeError):
                    continue
        return tuple(found)
