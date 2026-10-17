# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""REPL entry-point behavior: stdin feeding, continuation after errors,
quit/exit/EOF termination, unknown subcommand and the tty prompt branch."""

from __future__ import annotations

import io
import sys

import pytest

from mycad.cli.__main__ import main


def feed_stdin(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    """Point ``sys.stdin`` at an in-memory script (non-tty by default)."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))


class _FakeTty(io.StringIO):
    """StringIO that claims to be a tty so the prompt branch runs."""

    def isatty(self) -> bool:
        return True


def test_empty_argv_runs_repl_and_executes_lines(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    feed_stdin(monkeypatch, "new\nbox size_x=10 size_y=10 size_z=10\nquit\n")
    assert main([]) == 0
    assert "new document" in capsys.readouterr().out


def test_default_argv_reads_sys_argv(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["mycad"])
    feed_stdin(monkeypatch, "new\nquit\n")
    assert main(None) == 0
    assert "new document" in capsys.readouterr().out


def test_repl_continues_after_error_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    feed_stdin(
        monkeypatch,
        "new\nfrobnicate x=1\nbox size_x=10 size_y=10 size_z=10\nhistory\nquit\n",
    )
    assert main([]) == 1
    captured = capsys.readouterr()
    error_lines = [line for line in captured.err.splitlines() if line]
    assert len(error_lines) == 1
    assert "feature.box" in captured.out
    assert "[confirmed_by=cli-local]" in captured.out


def test_quit_stops_the_loop(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    feed_stdin(monkeypatch, "quit\nnew\n")
    assert main([]) == 0
    assert "new document" not in capsys.readouterr().out


def test_exit_stops_the_loop(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    feed_stdin(monkeypatch, "exit\nnew\n")
    assert main([]) == 0
    assert "new document" not in capsys.readouterr().out


def test_eof_ends_the_loop(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    feed_stdin(monkeypatch, "new\n")
    assert main([]) == 0
    assert "new document" in capsys.readouterr().out


def test_unknown_subcommand_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["frobnicate"]) == 2
    captured = capsys.readouterr()
    assert captured.err.strip() == "unknown subcommand: frobnicate"
    assert captured.out == ""


def test_help_subcommand_prints_the_usage_list(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["help"]) == 0
    out = capsys.readouterr().out
    assert "Subcommands:" in out
    assert "  gui" in out


def test_tty_stdin_prints_the_prompt(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "stdin", _FakeTty("quit\n"))
    assert main([]) == 0
    assert "mycad> " in capsys.readouterr().out
