# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Desktop dependency split and missing-extra CLI behavior."""

from __future__ import annotations

import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest

from mycad.cli import __main__ as cli_main
from mycad.cli.__main__ import main

REPO = Path(__file__).resolve().parents[2]
DESKTOP_DISTRIBUTIONS = {"pyside6", "pyqtgraph", "pyopengl"}


def test_desktop_stack_is_an_optional_extra() -> None:
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    base_dependencies = {
        item.split(">", 1)[0].split("=", 1)[0].lower() for item in project["dependencies"]
    }
    optional = project["optional-dependencies"]["desktop"]
    desktop_dependencies = {item.split(">", 1)[0].split("=", 1)[0].lower() for item in optional}

    assert DESKTOP_DISTRIBUTIONS.isdisjoint(base_dependencies)
    assert desktop_dependencies >= DESKTOP_DISTRIBUTIONS
    assert "build123d==0.11.1" in project["dependencies"]
    assert any(
        item.startswith("cadquery-ocp-novtk>=7.9.3.1.1,<7.9.4") for item in project["dependencies"]
    )


def test_gui_reports_install_command_when_qt_is_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _missing_gui_entrypoint() -> Callable[[], int]:
        raise ModuleNotFoundError("No module named 'PySide6'", name="PySide6")

    monkeypatch.setattr(cli_main, "_load_gui_entrypoint", _missing_gui_entrypoint)

    assert main(["gui"]) == 1
    assert "uv sync --extra desktop" in capsys.readouterr().err
