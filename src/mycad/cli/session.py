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

import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, cast

try:
    import readline  # noqa: F401  (optional: line editing when present)

    assert readline  # retain the optional import (no API of it is called)
except ImportError:
    pass

import mycad.app
from mycad.app import AppServices, new_document
from mycad.cli.plans import Outputs, load_plan_file
from mycad.commands.grammar import parse_line, to_cli
from mycad.commands.validation import validate_params
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


def _print_rollback(exc: BaseException, base: int) -> None:
    """stdout ``rolled back: <ordinals>`` for the steps a failed batch undid."""
    if isinstance(exc, BatchRollbackError) and exc.executed_ids:
        ordinals = ", ".join(str(base + i) for i in range(len(exc.executed_ids)))
        print(f"rolled back: {ordinals}")


def _batch_structure_error(head: str, rest: str, batch: Sequence[object] | None) -> str | None:
    """The one batch-structure rule set, shared by execution and ``validate``."""
    if rest:
        return f"{head} takes no arguments"
    if head == "begin-batch":
        return "nested begin-batch" if batch is not None else None
    if batch is None:
        return "end-batch without begin-batch"
    if not batch:
        # A zero-step plan violates the archive schema's minItems 1.
        return "empty batch: end-batch requires at least one command"
    return None


#: ``validate`` syntax rules for builtin lines (head -> argument requirement):
#: ``none`` takes no argument, ``required`` needs one, ``optional`` either.
_BUILTIN_ARITY: dict[str, str] = {
    "new": "none",
    "open": "required",
    "save": "optional",
    "export": "required",
    "meta": "required",
    "undo": "optional",
    "redo": "optional",
    "history": "optional",
    "help": "none",
    "quit": "none",
    "exit": "none",
}


def _builtin_syntax_error(head: str, rest: str) -> str | None:
    """Static (non-executing) usage check of one builtin line for ``validate``."""
    arity = _BUILTIN_ARITY[head]
    if arity == "none" and rest:
        return f"{head} takes no arguments"
    if arity == "required" and not rest:
        return f"{head} requires an argument"
    if head == "meta" and "=" not in rest:
        return "usage: meta <key>=<value>"
    if head in ("open", "save") and rest and not rest.endswith(".mc.json"):
        return f"{head} only supports .mc.json archives"
    if head == "history" and rest not in ("", "--json"):
        return "usage: history [--json]"
    return None


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

    def run_json(self, path: Path) -> int:
        """Execute a plan file per Appendix B.3 on its own fresh document.

        The session's current document is untouched. Outputs print one path
        per line in step/stl/archive order; with no ``outputs`` key all three
        land beside the plan file under its stem.
        """
        if not path.is_file():
            self._emit_error(f"file not found: {path}")
            return 2
        services = self._services
        try:
            validated = load_plan_file(path, services.registry)
            loaded = new_document(services)
            plan = Plan(list(validated.steps), plan_id=validated.plan_id)
            plan.confirm(actor="cli-local")
            loaded.bus.execute_batch(plan)
            for key, value in validated.plan_metadata.items():
                loaded.document.set_metadata(key, value)
            outputs = validated.outputs
            if outputs.step is None and outputs.stl is None and outputs.archive is None:
                outputs = Outputs(
                    step=path.with_name(f"{path.stem}.step"),
                    stl=path.with_name(f"{path.stem}.stl"),
                    archive=path.with_name(f"{path.stem}.mc.json"),
                )
            for target in (outputs.step, outputs.stl):
                if target is not None:
                    services.formats.resolve(target).write(services.kernel, target)
                    print(target)
            if outputs.archive is not None:
                save_document(loaded.document, outputs.archive)
                print(outputs.archive)
        except (MycadError, OSError) as exc:
            _print_rollback(exc, 0)
            self._emit_error(exc)
            return 1
        return 0

    def validate_file(self, path: Path) -> int:
        """Check a ``.json`` plan or ``.txt`` script without executing anything."""
        if not path.is_file():
            self._emit_error(f"file not found: {path}")
            return 2
        if path.suffix == ".json":
            try:
                count = len(load_plan_file(path, self._services.registry).steps)
            except MycadError as exc:
                self._emit_error(exc)
                return 1
            print(f"valid: plan {count} step(s)")
            return 0
        if path.suffix == ".txt":
            return self._validate_script(path)
        self._emit_error(f"validate supports .json plans and .txt scripts, got {path.name}")
        return 2

    def _validate_script(self, path: Path) -> int:
        """Static script check: N counts valid modeling lines (batch lines too)."""
        registry = self._services.registry
        batch: list[str] | None = None
        count = 0
        with path.open(encoding="utf-8") as handle:
            for raw_line in handle:
                stripped = raw_line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                head, _, rest = stripped.partition(" ")
                rest = rest.strip()
                if head in ("begin-batch", "end-batch"):
                    error = _batch_structure_error(head, rest, batch)
                    if error is not None:
                        self._emit_error(error)
                        return 2
                    batch = [] if head == "begin-batch" else None
                    continue
                if head in _BUILTIN_ARITY:
                    error = _builtin_syntax_error(head, rest)
                    if error is not None:
                        self._emit_error(error)
                        return 2
                    if head in ("quit", "exit"):
                        break
                    continue
                try:
                    command_id, params = parse_line(stripped, registry)
                    validate_params(registry.get(command_id), params, defs=registry.schema_defs)
                except MycadError as exc:
                    self._emit_error(exc)
                    return 1
                count += 1
                if batch is not None:
                    batch.append(command_id)
        if batch is not None:
            self._emit_error("unterminated batch")
            return 2
        print(f"valid: script {count} step(s)")
        return 0

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
        if rest == "--json":
            commands = self._doc.document.commands if self._doc is not None else ()
            entries: list[dict[str, object]] = []
            for command in commands:
                entry = asdict(command)
                if not command.amendments:
                    del entry["amendments"]
                entries.append(entry)
            print(json.dumps({"commands": entries}, ensure_ascii=False))
            return 0
        if rest:
            self._emit_error("usage: history [--json]")
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

    def list_commands(self, as_json: bool) -> int:
        """List every registered command; exit 0 always (skips are not errors)."""
        specs = [s for group in self._services.registry.list_by_category().values() for s in group]
        rows = sorted(
            (spec.cli.verb_aliases[0], spec.id, spec.summary_en, spec.label_zh) for spec in specs
        )
        if as_json:
            payload = {
                "commands": [
                    dict(zip(("verb", "id", "summary_en", "label_zh"), row, strict=True))
                    for row in rows
                ]
            }
            print(json.dumps(payload, ensure_ascii=False))
        else:
            for verb, command_id, summary, _zh in rows:
                print(f"{verb}\t{command_id}\t{summary}")
        return 0

    def list_plugins(self) -> int:
        """Report loaded plugins and skipped ones (reason codes, exit 0 always)."""
        for plugin in self._services.plugins.loaded():
            manifest = plugin.manifest
            assert manifest is not None  # loaded() guarantees a parsed manifest
            print(
                f"loaded: {manifest.id} v{manifest.version} api={manifest.api_version} "
                f"commands={len(plugin.commands)} formats={len(plugin.formats)}"
            )
        for name, reason in self._services.plugins.skipped():
            print(f"skipped: {name} reason={reason}")
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
        error = _batch_structure_error("begin-batch", rest, self._batch)
        if error is not None:
            self._emit_error(error)
            return 2
        self._batch = []
        return 0

    def _cmd_end_batch(self, rest: str) -> int:
        collected = self._batch
        error = _batch_structure_error("end-batch", rest, collected)
        if error is not None or collected is None:
            self._emit_error(error)
            return 2
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
            _print_rollback(exc, base)
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
