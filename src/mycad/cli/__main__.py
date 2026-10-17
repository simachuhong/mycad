# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Console entry point (T10a): ``mycad`` subcommand dispatch.

Exit-code contract (authoritative, no third category): 0 success; 2 CLI
usage error — unknown subcommand, missing/malformed subcommand argument,
missing script file; 1 modeling/runtime error — surfaced by the session
layer. The CLI is a top-level composition root: it builds the
application services itself (default entry-point discovery, identical to
library use) and drives a :class:`~mycad.cli.session.CliSession`.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO, cast

from mycad.app import build_app
from mycad.cli.session import HELP_TEXT, CliSession

__all__ = ["HELP_TEXT", "main"]


def _force_utf8(stream: TextIO) -> None:
    """Best-effort UTF-8 reconfigure; non-reconfigurable streams stay as-is."""
    reconfigure = cast("Callable[..., None] | None", getattr(stream, "reconfigure", None))
    if reconfigure is not None:
        reconfigure(encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch one ``mycad`` invocation; never raises, always returns a code."""
    _force_utf8(sys.stdout)
    _force_utf8(sys.stderr)
    args = list(sys.argv[1:]) if argv is None else list(argv)
    if not args or args == ["repl"]:
        return CliSession(build_app()).run_repl()
    if args == ["--help"] or args == ["-h"]:
        sys.stdout.write(HELP_TEXT)
        return 0
    sub, rest = args[0], args[1:]
    if sub == "help":
        if rest:
            print("help takes no arguments", file=sys.stderr)
            return 2
        sys.stdout.write(HELP_TEXT)
        return 0
    if sub == "run":
        as_json = rest[:1] == ["--json"]
        paths = rest[1:] if as_json else rest
        if not paths:
            print("run requires a script path", file=sys.stderr)
            return 2
        if len(paths) > 1:
            print(f"run: unexpected argument: {paths[1]}", file=sys.stderr)
            return 2
        session = CliSession(build_app())
        return session.run_json(Path(paths[0])) if as_json else session.run_script(Path(paths[0]))
    if sub == "validate":
        if len(rest) != 1:
            print("usage: mycad validate <file.json|file.txt>", file=sys.stderr)
            return 2
        return CliSession(build_app()).validate_file(Path(rest[0]))
    if sub == "commands":
        as_json = rest == ["--json"]
        if rest and not as_json:
            print("usage: mycad commands [--json]", file=sys.stderr)
            return 2
        # No-discovery app: the builtin listing stays exactly 8 even when a
        # demo plugin is installed editable in the environment.
        return CliSession(build_app()).list_commands(as_json)
    if sub == "plugins":
        if rest:
            print("plugins takes no arguments", file=sys.stderr)
            return 2
        return CliSession(build_app()).list_plugins()
    if sub == "gui":
        if rest:
            print("gui takes no arguments", file=sys.stderr)
            return 2
        from mycad.ui.entry import run_gui

        return run_gui()
    print(f"unknown subcommand: {sub}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
