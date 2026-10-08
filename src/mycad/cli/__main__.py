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
from mycad.cli.session import CliSession

__all__ = ["HELP_TEXT", "main"]

HELP_TEXT = """\
Usage: mycad <subcommand> [args]

Subcommands:
  repl                    Start the interactive REPL (default with no arguments)
  run <file.txt>          Execute an ASCII command script line by line
  validate <file>         Validate a plan or script without executing (T10b)
  commands [--json]       List registered commands (T10c)
  plugins                 List loaded plugins and skipped warnings (T10c)
  help                    Show this help text
"""


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
    sub, rest = args[0], args[1:]
    if sub == "help":
        if rest:
            print("help takes no arguments", file=sys.stderr)
            return 2
        sys.stdout.write(HELP_TEXT)
        return 0
    if sub == "run":
        if not rest:
            print("run requires a script path", file=sys.stderr)
            return 2
        if len(rest) > 1:
            print(f"run: unexpected argument: {rest[1]}", file=sys.stderr)
            return 2
        return CliSession(build_app()).run_script(Path(rest[0]))
    if sub in ("validate", "commands", "plugins"):
        # T10b/c placeholders: dispatch slots exist, behavior lands there.
        print(f"{sub}: not implemented yet", file=sys.stderr)
        return 2
    print(f"unknown subcommand: {sub}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
