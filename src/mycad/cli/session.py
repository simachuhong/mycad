# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""REPL/script session (T10a): builtin document commands + batch transactions.

Exit-code contract (authoritative): 0 success; 2 CLI usage error — unknown
builtin, missing/malformed argument, missing file, ``open``/``save`` wrong
extension, nested ``begin-batch``, ``end-batch`` without an open batch, empty
batch, unterminated batch at EOF/quit; 1 modeling/runtime error — unknown
command id, validation/geometry errors, batch rollback. Every stderr message
is exactly one line (first line of ``str(e)``); no tracebacks leak.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, cast

try:
    import readline  # noqa: F401  (optional: line editing when present)

    assert readline  # retain the optional import (no API of it is called)
except ImportError:
    pass

import mycad.app
from mycad.app import AppServices, new_document
from mycad.commands.grammar import parse_line, to_cli
from mycad.core.document import AFFECTED_OBJECTS, AffectedObject, PlannedCommand
from mycad.core.exceptions import BatchRollbackError, MycadError
from mycad.core.persistence import LoadedDocument, open_document, save_document
from mycad.core.plan import Plan

if TYPE_CHECKING:
    from mycad.commands.registry import CommandRegistry
    from mycad.core.handlers import CommandHandler
    from mycad.plugins.manager import PluginManager

__all__ = ["CliSession"]

#: The app-layer handler-map assembler (``mycad.app._handler_map``), reached
#: dynamically: it is module-private by design and the CLI must not re-derive
#: the assembly, so ``getattr`` + ``cast`` satisfies strict checking without
#: duplicating the logic or weakening the gate.
_assemble_handlers = cast(
    "Callable[[CommandRegistry, PluginManager], dict[str, CommandHandler]]",
    getattr(mycad.app, "_handler_map"),  # noqa: B009 (private bridge, see above)
)

#: Sentinel return code for ``quit``/``exit`` — an internal stop signal handed
#: to the loop drivers, never a process exit code (contract codes are 0/1/2).
_QUIT_REQUESTED = -1


class CliSession:
    """One document session driven by text lines (REPL or script file)."""

    def __init__(self, services: AppServices) -> None:
        self._services = services
        self._doc: LoadedDocument | None = None
        self._archive_path: Path | None = None
        self._batch: list[tuple[str, dict[str, object]]] | None = None

    def run_repl(self) -> int:
        """Read lines from stdin until quit/exit/EOF; errors never stop the loop.

        tty mode prints a ``mycad> `` prompt before each line. The session exit
        code accumulates the worst line-level code; an unterminated batch at
        loop end is a usage error (2) overriding the accumulation.
        """
        interactive = sys.stdin.isatty()
        code = 0
        while True:
            if interactive:
                print("mycad> ", end="", flush=True)
            line = sys.stdin.readline()
            if not line:
                break
            result = self.execute_line(line)
            if result == _QUIT_REQUESTED:
                break
            if result > code:
                code = result
        return self._finish(code)

    def run_script(self, path: Path) -> int:
        """Execute a script file line by line; the first error stops the run.

        A missing file is rejected with 2 before any content is examined.
        ``#`` comments and blank lines are skipped. An unterminated batch at
        end-of-file (or at ``quit``) is a usage error and executes nothing.
        """
        if not path.is_file():
            self._emit_error(f"file not found: {path}")
            return 2
        with path.open(encoding="utf-8") as handle:
            for raw_line in handle:
                result = self.execute_line(raw_line)
                if result == _QUIT_REQUESTED:
                    break
                if result != 0:
                    return result
        return self._finish(0)

    def execute_line(self, line: str) -> int:
        """Execute one text line; never raises.

        Returns 0/1/2 by the contract, or the internal ``_QUIT_REQUESTED``
        sentinel for ``quit``/``exit`` (loop drivers stop on it).
        """
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            return 0
        parts = stripped.split(None, 1)
        head = parts[0]
        rest = parts[1] if len(parts) > 1 else ""
        builtin = self._BUILTIN_HANDLERS.get(head)
        if builtin is not None:
            return builtin(self, rest)
        if head == "begin-batch":
            return self._cmd_begin_batch(rest)
        if head == "end-batch":
            return self._cmd_end_batch(rest)
        return self._run_modeling_line(stripped)

    def _run_modeling_line(self, stripped: str) -> int:
        """Grammar-parse then either collect (inside batch) or execute a line.

        A parse failure inside a batch aborts the batch (nothing collected is
        ever executed — rollback-by-never-running semantics) and reports a
        runtime error (1).
        """
        try:
            command_id, params = parse_line(stripped, self._services.registry)
        except MycadError as exc:
            if self._batch is not None:
                self._batch = None
            self._emit_error(exc)
            return 1
        if self._batch is not None:
            self._batch.append((command_id, params))
            return 0
        try:
            self._require_doc().bus.execute(command_id, params, confirmed_by="cli-local")
        except MycadError as exc:
            self._emit_error(exc)
            return 1
        return 0

    def _require_doc(self) -> LoadedDocument:
        """Lazily create the document on first modeling use (REPL semantics)."""
        if self._doc is None:
            self._doc = new_document(self._services)
        return self._doc

    def _emit_error(self, message: object) -> None:
        """Print exactly one stderr line (first line of the message)."""
        first = str(message).split("\n", 1)[0]
        if first:
            print(first, file=sys.stderr)

    def _finish(self, code: int) -> int:
        """Shared loop-end gate: an unterminated batch is a usage error (2)."""
        if self._batch is not None:
            self._emit_error("unterminated batch")
            return 2
        return code

    # ------------------------------------------------------------------
    # builtin document commands (§3.3)
    # ------------------------------------------------------------------

    def _cmd_new(self, rest: str) -> int:
        if rest:
            self._emit_error("new takes no arguments")
            return 2
        self._doc = new_document(self._services)
        self._archive_path = None
        print("new document")
        return 0

    def _cmd_open(self, rest: str) -> int:
        if not rest:
            self._emit_error("open requires a path")
            return 2
        path = Path(rest)
        # Extension gate FIRST — before any registry or file access.
        if not path.name.endswith(".mc.json"):
            self._emit_error("open only supports .mc.json archives")
            return 2
        if not path.is_file():
            self._emit_error(f"file not found: {path}")
            return 2
        handlers = _assemble_handlers(self._services.registry, self._services.plugins)
        try:
            self._doc = open_document(
                path,
                registry=self._services.registry,
                kernel=self._services.kernel,
                handlers=handlers,
            )
        except MycadError as exc:
            self._emit_error(exc)
            return 1
        self._archive_path = path
        print(f"opened {path}")
        return 0

    def _cmd_save(self, rest: str) -> int:
        if rest:
            path = Path(rest)
            if not path.name.endswith(".mc.json"):
                self._emit_error("save only supports .mc.json archives")
                return 2
        elif self._archive_path is not None:
            path = self._archive_path
        else:
            self._emit_error("save requires a path for an unsaved document")
            return 2
        try:
            save_document(self._require_doc().document, path)
        except (MycadError, OSError) as exc:
            self._emit_error(exc)
            return 1
        self._archive_path = path
        print(path)
        return 0

    def _cmd_export(self, rest: str) -> int:
        if not rest:
            self._emit_error("export requires a path")
            return 2
        path = Path(rest)
        try:
            provider = self._services.formats.resolve(path)
            provider.write(self._services.kernel, path)
        except (MycadError, OSError) as exc:
            self._emit_error(exc)
            return 1
        print(path)
        return 0

    def _cmd_meta(self, rest: str) -> int:
        if not rest or "=" not in rest:
            self._emit_error("usage: meta <key>=<value>")
            return 2
        key, _, raw_value = rest.partition("=")
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        try:
            self._require_doc().document.set_metadata(key, value)
        except MycadError as exc:
            self._emit_error(exc)
            return 1
        print(f"{key}={value}")
        return 0

    def _cmd_undo(self, rest: str) -> int:
        count = self._parse_count("undo", rest)
        if count is None:
            return 1
        try:
            self._require_doc().bus.undo(count)
        except MycadError as exc:
            self._emit_error(exc)
            return 1
        return 0

    def _cmd_redo(self, rest: str) -> int:
        count = self._parse_count("redo", rest)
        if count is None:
            return 1
        try:
            self._require_doc().bus.redo(count)
        except MycadError as exc:
            self._emit_error(exc)
            return 1
        return 0

    def _parse_count(self, action: str, rest: str) -> int | None:
        """Parse the optional ``n`` for undo/redo; malformed -> runtime error."""
        if not rest:
            return 1
        try:
            count = int(rest)
        except ValueError:
            count = -1
        if count < 1:
            self._emit_error(f"{action}: n must be an integer >= 1, got {rest!r}")
            return None
        return count

    def _cmd_history(self, rest: str) -> int:
        if rest:
            self._emit_error("history takes no arguments")
            return 2
        if self._doc is None:
            return 0
        for command in self._doc.document.commands:
            line = to_cli(command.id, command.params, self._services.registry)
            actor = (
                f"  [confirmed_by={command.confirmed_by}]"
                if command.confirmed_by is not None
                else ""
            )
            print(f"{command.ordinal}: {command.id} {line}{actor}")
        return 0

    def _cmd_help(self, rest: str) -> int:
        if rest:
            self._emit_error("help takes no arguments")
            return 2
        from mycad.cli.__main__ import HELP_TEXT

        sys.stdout.write(HELP_TEXT)
        return 0

    def _cmd_quit(self, rest: str) -> int:
        if rest:
            self._emit_error("quit takes no arguments")
            return 2
        return _QUIT_REQUESTED

    # ------------------------------------------------------------------
    # batch state machine (§3.4)
    # ------------------------------------------------------------------

    def _cmd_begin_batch(self, rest: str) -> int:
        if rest:
            self._emit_error("begin-batch takes no arguments")
            return 2
        if self._batch is not None:
            self._emit_error("nested begin-batch")
            return 2
        self._batch = []
        return 0

    def _cmd_end_batch(self, rest: str) -> int:
        if rest:
            self._emit_error("end-batch takes no arguments")
            return 2
        if self._batch is None:
            self._emit_error("end-batch without begin-batch")
            return 2
        if not self._batch:
            # A zero-step plan violates the archive schema's minItems 1.
            self._emit_error("empty batch: end-batch requires at least one command")
            return 2
        collected = self._batch
        steps: list[PlannedCommand] = []
        for command_id, params in collected:
            spec = self._services.registry.get(command_id)
            steps.append(
                PlannedCommand(
                    id=command_id,
                    version=spec.version,
                    params=params,
                    summary_en=spec.summary_en,
                    affected_object=cast("AffectedObject", AFFECTED_OBJECTS[command_id]),
                )
            )
        base = len(self._require_doc().document.commands)
        plan = Plan(steps)
        plan.confirm(actor="cli-local")
        try:
            self._require_doc().bus.execute_batch(plan)
        except MycadError as exc:
            if isinstance(exc, BatchRollbackError) and exc.executed_ids:
                ordinals = ", ".join(str(base + i) for i in range(len(exc.executed_ids)))
                print(f"rolled back: {ordinals}")
            self._emit_error(exc)
            self._batch = None
            return 1
        self._batch = None
        return 0

    #: Builtin dispatch table: first token -> method taking the rest of the
    #: line. ``begin-batch``/``end-batch`` are handled separately in
    #: ``execute_line`` (batch state machine), not through this table.
    _BUILTIN_HANDLERS: ClassVar[dict[str, Callable[[CliSession, str], int]]] = {
        "new": _cmd_new,
        "open": _cmd_open,
        "save": _cmd_save,
        "export": _cmd_export,
        "meta": _cmd_meta,
        "undo": _cmd_undo,
        "redo": _cmd_redo,
        "history": _cmd_history,
        "help": _cmd_help,
        "quit": _cmd_quit,
        "exit": _cmd_quit,
    }
