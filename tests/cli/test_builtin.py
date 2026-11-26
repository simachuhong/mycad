# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Builtin document commands (§3.3): new/open/save/export/meta/undo/redo/
history driven through ``CliSession.execute_line``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mycad.app import AppServices, build_app
from mycad.cli.session import CliSession

BOX_LINE = "box size_x=10 size_y=10 size_z=10"


@pytest.fixture()
def services() -> AppServices:
    return build_app(discoverers=[])


@pytest.fixture()
def session(services: AppServices) -> CliSession:
    return CliSession(services)


def test_new_then_modeling_line_succeeds(
    session: CliSession, capsys: pytest.CaptureFixture[str]
) -> None:
    assert session.execute_line("new") == 0
    assert session.execute_line("cylinder radius=5 height=10 mode=new") == 0
    assert "new document" in capsys.readouterr().out


@pytest.mark.parametrize("failure", ["unavailable", "timeout", "encoding", "invalid_response"])
def test_legacy_dxf_export_font_worker_failure_preserves_target(
    services: AppServices, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    import subprocess
    from uuid import uuid4

    from mycad import app
    from mycad.cli import legacy_dxf
    from mycad.core.geometric_tolerance import FeatureControlFrame, ToleranceRow

    loaded = app.new_workspace_document(services, kind="sketch")
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (20, 20), leader_target_mm=(0, 0)
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    revision = loaded.document.revision
    target = tmp_path / "existing.dxf"
    target.write_bytes(b"original")

    def fail(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if failure == "timeout":
            raise subprocess.TimeoutExpired("worker", 30)
        if failure == "encoding":
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid byte")
        if failure == "unavailable":
            return subprocess.CompletedProcess("worker", 1, "", "missing Qt")
        return subprocess.CompletedProcess("worker", 0, "{}", "")

    monkeypatch.setattr(legacy_dxf.subprocess, "run", fail)
    messages: list[str] = []
    assert CliSession(services, doc=loaded, messages=messages).execute_line(f"export {target}") == 1
    assert target.read_bytes() == b"original"
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert loaded.document.revision == revision


def test_dxf_without_legacy_leaders_does_not_launch_font_worker(
    services: AppServices, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad import app
    from mycad.cli import legacy_dxf
    from mycad.core.geometric_tolerance import FeatureControlFrame, ToleranceRow

    loaded = app.new_workspace_document(services, kind="sketch")
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (20, 20))
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")

    def unexpected(*_args: object, **_kwargs: object) -> None:
        pytest.fail("ordinary DXF export must not start the font worker")

    monkeypatch.setattr(legacy_dxf.subprocess, "run", unexpected)
    target = tmp_path / "ordinary.dxf"
    assert CliSession(services, doc=loaded).execute_line(f"export {target}") == 0
    assert target.exists()


@pytest.mark.parametrize("failure", ["timeout", "invalid_response"])
def test_legacy_datum_font_worker_failure_preserves_target(
    services: AppServices, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    import subprocess
    from uuid import uuid4

    from mycad import app
    from mycad.cli import legacy_dxf
    from mycad.core.geometric_tolerance import DatumIdentifier

    loaded = app.new_workspace_document(services, kind="sketch")
    datum = DatumIdentifier(uuid4().hex, "A", (10, 10), (0, 0))
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    revision = loaded.document.revision
    target = tmp_path / "existing.dxf"
    target.write_bytes(b"original")

    def fail(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if failure == "timeout":
            raise subprocess.TimeoutExpired("worker", 30)
        return subprocess.CompletedProcess("worker", 0, "{}", "")

    monkeypatch.setattr(legacy_dxf.subprocess, "run", fail)
    messages: list[str] = []
    assert CliSession(services, doc=loaded, messages=messages).execute_line(f"export {target}") == 1
    assert target.read_bytes() == b"original"
    assert loaded.document.revision == revision
    assert any("旧基准" in message for message in messages)


def test_legacy_datum_without_qt_uses_warned_headless_fallback(
    services: AppServices, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess
    from uuid import uuid4

    from mycad import app
    from mycad.cli import legacy_dxf
    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    loaded = app.new_workspace_document(services, kind="sketch")
    datum = DatumIdentifier(uuid4().hex, "A", (10, 10), (0, 0))
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    monkeypatch.setattr(
        legacy_dxf.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            "worker", 1, "", "ModuleNotFoundError: No module named 'PySide6'"
        ),
    )
    messages: list[str] = []
    target = tmp_path / "fallback.dxf"
    assert CliSession(services, doc=loaded, messages=messages).execute_line(f"export {target}") == 0
    assert read_sketch_dxf(target).datum_identifiers[0].datum_id == datum.datum_id
    assert any("桌面字体组件未安装" in message and "估算" in message for message in messages)


@pytest.mark.parametrize("value", [[True, 5], [0, 5], [float("nan"), 5], [5], [5, 5, 5]])
def test_legacy_datum_rejects_malformed_worker_dimensions_without_overwrite(
    services: AppServices, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: object
) -> None:
    import subprocess
    from uuid import uuid4

    from mycad import app
    from mycad.cli import legacy_dxf
    from mycad.core.geometric_tolerance import DatumIdentifier

    loaded = app.new_workspace_document(services, kind="sketch")
    datum = DatumIdentifier(uuid4().hex, "A", (10, 10), (0, 0))
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    response = json.dumps(
        {
            "anchors": {},
            "skipped": {},
            "bounds": {},
            "notices": [],
            "datum_boxes": {datum.datum_id: value},
        }
    )
    monkeypatch.setattr(
        legacy_dxf.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess("worker", 0, response, ""),
    )
    target = tmp_path / "existing.dxf"
    target.write_bytes(b"original")
    assert CliSession(services, doc=loaded).execute_line(f"export {target}") == 1
    assert target.read_bytes() == b"original"


def test_shared_datum_without_legacy_frames_does_not_launch_font_worker(
    services: AppServices, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad import app
    from mycad.cli import legacy_dxf
    from mycad.core.geometric_tolerance import DatumIdentifier

    loaded = app.new_workspace_document(services, kind="sketch")
    datum = DatumIdentifier(uuid4().hex, "A", (10, 10), (0, 0), layout_mode="shared")
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")

    def unexpected(*_args: object, **_kwargs: object) -> None:
        pytest.fail("shared datum export must not start the font worker")

    monkeypatch.setattr(legacy_dxf.subprocess, "run", unexpected)
    target = tmp_path / "shared.dxf"
    assert CliSession(services, doc=loaded).execute_line(f"export {target}") == 0
    assert target.exists()


def test_legacy_datum_does_not_intercept_third_party_dxf_provider(
    services: AppServices, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad import app
    from mycad.cli import legacy_dxf
    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.core.ports import ExportableKernel
    from mycad.formats.base import FormatProvider

    loaded = app.new_workspace_document(services, kind="sketch")
    datum = DatumIdentifier(uuid4().hex, "A", (10, 10), (0, 0))
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")

    def write(_geometry: ExportableKernel, path: Path) -> None:
        path.write_bytes(b"third-party")

    provider = FormatProvider("custom", "test", 0, (".dxf",), False, True, "shape", write)
    services.formats.register(provider)

    def unexpected(*_args: object, **_kwargs: object) -> None:
        pytest.fail("custom DXF provider must not start the font worker")

    monkeypatch.setattr(legacy_dxf.subprocess, "run", unexpected)
    target = tmp_path / "third-party.dxf"
    assert CliSession(services, doc=loaded).execute_line(f"export {target}") == 0
    assert target.read_bytes() == b"third-party"


def test_legacy_frame_and_datum_without_qt_do_not_overwrite_target(
    services: AppServices, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess
    from uuid import uuid4

    from mycad import app
    from mycad.cli import legacy_dxf
    from mycad.core.geometric_tolerance import DatumIdentifier, FeatureControlFrame, ToleranceRow

    loaded = app.new_workspace_document(services, kind="sketch")
    datum = DatumIdentifier(uuid4().hex, "A", (10, 10), (0, 0))
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (20, 20), leader_target_mm=(0, 0)
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    monkeypatch.setattr(
        legacy_dxf.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            "worker", 1, "", "ModuleNotFoundError: No module named 'PySide6'"
        ),
    )
    target = tmp_path / "existing.dxf"
    target.write_bytes(b"original")
    assert CliSession(services, doc=loaded).execute_line(f"export {target}") == 1
    assert target.read_bytes() == b"original"


@pytest.mark.parametrize("suffix", [".my3d", ".my2d", ".MY3D"])
def test_native_archive_suffix_roundtrip(session: CliSession, tmp_path: Path, suffix: str) -> None:
    archive = tmp_path / f"native{suffix}"
    assert session.execute_line("new") == 0
    assert session.execute_line(BOX_LINE) == 0
    assert session.execute_line(f"save {archive}") == 0
    assert archive.is_file()
    assert session.execute_line("new") == 0
    assert session.execute_line(f"open {archive}") == 0
    script = tmp_path / "check.txt"
    script.write_text(f"open {archive}\nsave {archive}\n", encoding="utf-8")
    assert session.validate_file(script) == 0


def test_intersect_alias_executes_and_undo_restores_previous_model(
    session: CliSession, services: AppServices
) -> None:
    assert session.execute_line("new") == 0
    assert session.execute_line("box size_x=10 size_y=10 size_z=10") == 0
    assert (
        session.execute_line(
            "intersect tool.type=box tool.size_x=5 tool.size_y=5 tool.size_z=5 "
            "tool.center=[2.5,0,0]"
        )
        == 0
    )
    assert services.kernel.mass_properties().volume == pytest.approx(125.0, abs=1e-6)

    assert session.execute_line("undo") == 0
    assert services.kernel.mass_properties().volume == pytest.approx(1000.0, abs=1e-6)


def test_meta_roundtrip_and_echo(session: CliSession, capsys: pytest.CaptureFixture[str]) -> None:
    session.execute_line("new")
    assert session.execute_line("meta part_no=ABC-123") == 0
    assert "part_no=ABC-123" in capsys.readouterr().out


def test_meta_strips_surrounding_quotes(
    session: CliSession, capsys: pytest.CaptureFixture[str]
) -> None:
    session.execute_line("new")
    assert session.execute_line('meta material="Steel 42CrMo4"') == 0
    assert "material=Steel 42CrMo4" in capsys.readouterr().out


def test_meta_unknown_key_is_a_runtime_error(
    session: CliSession, capsys: pytest.CaptureFixture[str]
) -> None:
    session.execute_line("new")
    assert session.execute_line("meta color=red") == 1
    assert "unknown metadata key" in capsys.readouterr().err


def test_meta_missing_equals_is_a_usage_error(
    session: CliSession, capsys: pytest.CaptureFixture[str]
) -> None:
    session.execute_line("new")
    assert session.execute_line("meta part_no") == 2
    assert capsys.readouterr().err.strip() == "usage: meta <key>=<value>"


def test_save_without_path_and_no_archive(
    session: CliSession, capsys: pytest.CaptureFixture[str]
) -> None:
    session.execute_line("new")
    assert session.execute_line("save") == 2
    assert capsys.readouterr().err.strip() == "save requires a path for an unsaved document"


def test_save_explicit_path_then_implicit_overwrite(
    session: CliSession, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = tmp_path / "part.mc.json"
    session.execute_line("new")
    session.execute_line(BOX_LINE)
    assert session.execute_line(f"save {archive}") == 0
    assert str(archive) in capsys.readouterr().out
    session.execute_line(BOX_LINE)
    assert session.execute_line("save") == 0  # implicit overwrite of the archive
    payload = json.loads(archive.read_text(encoding="utf-8"))
    assert len(payload["commands"]) == 2


def test_save_wrong_extension_is_a_usage_error(
    session: CliSession, capsys: pytest.CaptureFixture[str]
) -> None:
    session.execute_line("new")
    assert session.execute_line("save /tmp/whatever.step") == 2
    assert "save only supports .mc.json" in capsys.readouterr().err


def test_open_wrong_extension_never_touches_the_format_resolver(
    services: AppServices,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    resolve_calls: list[Path] = []
    real_resolve = services.formats.resolve

    def spy(path: Path) -> object:
        resolve_calls.append(path)
        return real_resolve(path)

    monkeypatch.setattr(services.formats, "resolve", spy)
    session = CliSession(services)
    assert session.execute_line("open /tmp/whatever.step") == 2
    assert resolve_calls == []
    assert capsys.readouterr().err.strip() == "open only supports .mc.json, .my2d, .my3d archives"


def test_open_missing_file_is_a_usage_error(
    session: CliSession, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert session.execute_line(f"open {tmp_path / 'nope.mc.json'}") == 2
    assert "file not found" in capsys.readouterr().err


def test_open_roundtrip_preserves_history(
    session: CliSession, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = tmp_path / "round.mc.json"
    session.execute_line("new")
    session.execute_line(BOX_LINE)
    session.execute_line(f"save {archive}")
    session.execute_line("new")  # wipe the in-memory document
    assert session.execute_line(f"open {archive}") == 0
    session.execute_line("history")
    out = capsys.readouterr().out
    assert "opened" in out
    assert out.count(": feature.box ") == 1


def test_export_step_and_stl_produce_files(
    session: CliSession, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    session.execute_line("new")
    session.execute_line("cylinder radius=5 height=10 mode=new")
    for name in ("part.step", "part.stl"):
        target = tmp_path / name
        assert session.execute_line(f"export {target}") == 0
        assert target.is_file()
        assert target.stat().st_size > 0
        assert str(target) in capsys.readouterr().out


def test_export_unknown_extension_is_a_runtime_error(
    session: CliSession, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    session.execute_line("new")
    session.execute_line("cylinder radius=5 height=10 mode=new")
    assert session.execute_line(f"export {tmp_path / 'part.obj'}") == 1
    assert "obj" in capsys.readouterr().err


def test_undo_redo_counts_and_invalid_history(
    session: CliSession, capsys: pytest.CaptureFixture[str]
) -> None:
    session.execute_line("new")
    session.execute_line(BOX_LINE)
    assert session.execute_line("undo") == 0
    session.execute_line("history")
    assert ": feature.box" not in capsys.readouterr().out
    assert session.execute_line("redo") == 0
    session.execute_line("history")
    assert ": feature.box" in capsys.readouterr().out
    assert session.execute_line("undo 5") == 1  # history has 1, requested 5
    assert session.execute_line("undo abc") == 1  # malformed count
    assert session.execute_line("redo 0") == 1
    assert capsys.readouterr().err != ""


def test_history_line_format(session: CliSession, capsys: pytest.CaptureFixture[str]) -> None:
    session.execute_line("new")
    session.execute_line(BOX_LINE)
    session.execute_line("history")
    (history_line,) = [
        line for line in capsys.readouterr().out.splitlines() if ": feature.box " in line
    ]
    assert history_line.startswith("0: feature.box box ")
    assert "center=[0,0,0]" in history_line
    assert history_line.endswith("  [confirmed_by=cli-local]")


def test_history_is_empty_for_a_fresh_document(
    session: CliSession, capsys: pytest.CaptureFixture[str]
) -> None:
    session.execute_line("new")
    assert session.execute_line("history") == 0
    out = capsys.readouterr().out
    assert [line for line in out.splitlines() if ": feature." in line] == []
