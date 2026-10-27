# P2-24 — Archive and recovery contract

Date: 2026-10-24

## Decision and behavior

- `.mc.json` v1 remains frozen. A separately authored two-command archive fixture is opened by the existing loader and checks all six command audit fields without generating the fixture through the current writer.
- Replace, temp-write, and temp-flush failure regressions verify that an existing archive's bytes remain unchanged, the document stays dirty, no `document_saved` event is emitted, and any partial temporary file is removed.
- Save As now binds the chosen path only after `_store_document()` confirms a successful write. A failed Save As leaves the document dirty and unbound to the failed path.
- [ADR-008](../../docs/adr/ADR-008-persistence-reproducibility-and-recovery.md) defines replay limits, runtime-only identity, command history versus append-only audit, v2 triggers, pure migration requirements, and the current atomic-replacement limit.

## Verification

```text
uv run pytest tests/core/test_persistence.py tests/test_exceptions.py tests/ui/test_document_lifecycle.py -q
44 passed in 18.90s
```

The initial Save As regression failed because `_document_path` was assigned after the write error; it passes after the fix. The static fixture regression was first run without the fixture and failed with `FileNotFoundError`; it passes once the independent v1 fixture was added. The added temp-write and temp-flush regressions failed before the cleanup fix because both left a partial `.tmp`, then passed after recording the path immediately after opening the file. The failed Save As check now verifies behavior by triggering Save again and observing that the dialog reopens, rather than inspecting a private field. Ruff and basedpyright passed for all four changed source/test files.

```text
uv run ruff check src/mycad/core/persistence.py src/mycad/ui/main_window.py tests/core/test_persistence.py tests/ui/test_document_lifecycle.py
All checks passed!
uv run ruff format --check src/mycad/core/persistence.py src/mycad/ui/main_window.py tests/core/test_persistence.py tests/ui/test_document_lifecycle.py
4 files already formatted
uv run basedpyright src/mycad/core/persistence.py src/mycad/ui/main_window.py tests/core/test_persistence.py tests/ui/test_document_lifecycle.py
0 errors, 0 warnings, 0 notes
git diff --check
passed
```

## Compatibility and limits

No v1 fields or geometry dependency versions changed. The migration registry remains empty; no v2 schema, stable persisted IDs, backups, autosave, recovery journal, or `fsync` guarantee was added. `os.replace` does not establish power-loss durability. P2-24 closes the contract and ordinary failure path only.
