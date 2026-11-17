# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Persistence tests (T6d): migrations chain, open exception matrix, round trips."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TextIO, cast

import pytest

from mycad.core import migrations
from mycad.core.handlers import HandlerContext
from mycad.core.measurements import MeasurementRequest, MeasurementResult
from mycad.core.migrations import Migration, migrate, register


def test_migrate_v1_identity_returns_same_object() -> None:
    data: dict[str, object] = {"version": 1, "commands": []}
    assert migrate(data) is data


def test_registered_hop_advances_to_supported_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(migrations, "_REGISTRY", [])
    register(Migration(1, 2, lambda data: {**data, "version": 2}))
    data: dict[str, object] = {"version": 1, "payload": "x"}
    assert migrate(data, supported_version=2) == {"version": 2, "payload": "x"}


def test_unknown_version_raises_valueerror_naming_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(migrations, "_REGISTRY", [])
    register(Migration(1, 2, lambda data: {**data, "version": 2}))
    with pytest.raises(ValueError, match="version 3"):
        migrate({"version": 3}, supported_version=1)
    with pytest.raises(ValueError, match="1 migrations registered"):
        migrate({"version": 3}, supported_version=1)


def test_factory_registry_ships_empty() -> None:
    shipped = cast("list[Migration]", getattr(migrations, "_REGISTRY"))  # noqa: B009
    assert shipped == []


class FakeKernel:
    """Kernel double: records applies; ``fail_when`` injects failures."""

    def __init__(self) -> None:
        self.applied: list[tuple[str, dict[str, object]]] = []
        self.fail_when: Callable[[int, str, dict[str, object]], Exception | None] | None = None
        self._apply_total = 0

    def reset(self) -> None:
        self.applied.clear()

    def apply(self, command_id: str, params: Mapping[str, object]) -> None:
        n = self._apply_total
        self._apply_total += 1
        if self.fail_when is not None:
            exc = self.fail_when(n, command_id, dict(params))
            if exc is not None:
                raise exc
        self.applied.append((command_id, dict(params)))

    def measure(self, request: MeasurementRequest) -> MeasurementResult:
        return MeasurementResult(
            value=None,
            unit="mm³",
            revision=request.revision,
            description="fake measurement",
            error="geometry is unavailable in FakeKernel",
        )


class EchoHandler:
    """Echoes its bound id; asserts ctx.command_id agreement."""

    def __init__(self, command_id: str) -> None:
        self.command_id = command_id

    def handle(self, params: Mapping[str, object], ctx: HandlerContext) -> object | None:
        assert ctx.command_id == self.command_id
        return self.command_id


class VersionMarkerHandler:
    """Record handler selection in the fake geometry for replay assertions."""

    def __init__(self, command_id: str, version: int) -> None:
        self.command_id = command_id
        self.version = version

    def handle(self, params: Mapping[str, object], ctx: HandlerContext) -> object | None:
        assert ctx.command_version == self.version
        ctx.kernel.apply(self.command_id, {**params, "handler_version": self.version})
        return None


# -- open exception matrix (appended batch; E402 suppressed by design) --------
import json  # noqa: E402

from mycad.commands.demo import demo_registry  # noqa: E402
from mycad.commands.registry import CommandRegistry  # noqa: E402
from mycad.commands.spec import CliSyntax, CommandSpec  # noqa: E402
from mycad.core.bus import CommandBus  # noqa: E402
from mycad.core.document import Document  # noqa: E402
from mycad.core.exceptions import (  # noqa: E402
    ArchiveVersionError,
    GeometryBuildError,
    UnknownCommandError,
    ValidationError,
)
from mycad.core.handlers import BuiltinModelingHandler, CommandHandler  # noqa: E402
from mycad.core.persistence import open_document, save_document  # noqa: E402

_SEL_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "surface": {"type": "string", "enum": ["plane", "cylinder"]},
        "axis": {"type": "string"},
    },
    "required": ["surface"],
    "additionalProperties": False,
}


def make_assembly() -> tuple[CommandRegistry, dict[str, CommandHandler], FakeKernel]:
    """demo registry + demo.sel spec + cylinder/sel handlers + fake kernel."""
    reg = demo_registry()
    reg.register(CommandSpec("demo.sel", 1, "sel", "选择器", _SEL_SCHEMA, CliSyntax(("demo.sel",))))
    fake = FakeKernel()
    handlers: dict[str, CommandHandler] = {
        "feature.cylinder": BuiltinModelingHandler("feature.cylinder"),
        "demo.sel": EchoHandler("demo.sel"),
    }
    return reg, handlers, fake


def seed_archive(path: Path) -> None:
    """Two executed cylinders saved to ``path`` (the tampering baseline)."""
    reg, handlers, fake = make_assembly()
    doc = Document(reg)
    bus = CommandBus(doc, reg, fake, handlers)
    bus.execute("feature.cylinder", {"radius": 1.0, "height": 2.0})
    bus.execute("feature.cylinder", {"radius": 2.0, "height": 2.0})
    save_document(doc, path)


def tamper(path: Path, mutate: Callable[[dict[str, object]], None]) -> Path:
    """Load the archive at ``path``, apply ``mutate`` and rewrite it in place."""
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_open_malformed_json_is_validation_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.mc.json"
    bad.write_text("{not json", encoding="utf-8")
    reg, handlers, fake = make_assembly()
    with pytest.raises(ValidationError, match="malformed JSON"):
        open_document(bad, registry=reg, kernel=fake, handlers=handlers)
    assert fake.applied == []


def test_open_unknown_metadata_key_rejects_before_any_construction(tmp_path: Path) -> None:
    path = tmp_path / "a.mc.json"
    seed_archive(path)

    def add_bogus(data: dict[str, object]) -> None:
        cast("dict[str, object]", data["metadata"])["bogus"] = "x"

    reg, handlers, fake = make_assembly()
    with pytest.raises(ValidationError, match="bogus"):
        open_document(tamper(path, add_bogus), registry=reg, kernel=fake, handlers=handlers)
    assert fake.applied == []


def test_open_unknown_top_level_key_rejected(tmp_path: Path) -> None:
    path = tmp_path / "a.mc.json"
    seed_archive(path)
    reg, handlers, fake = make_assembly()
    with pytest.raises(ValidationError, match="extra"):
        open_document(
            tamper(path, lambda d: d.update(extra=1)), registry=reg, kernel=fake, handlers=handlers
        )


def test_open_missing_handler_names_ordinal_and_id(tmp_path: Path) -> None:
    path = tmp_path / "a.mc.json"
    seed_archive(path)
    reg, handlers, _fake = make_assembly()
    del handlers["feature.cylinder"]
    with pytest.raises(UnknownCommandError) as excinfo:
        open_document(path, registry=reg, kernel=FakeKernel(), handlers=handlers)
    message = str(excinfo.value)
    assert "ordinal 0" in message
    assert "feature.cylinder" in message


def test_v1_archive_replays_with_its_schema_and_handler_version(tmp_path: Path) -> None:
    command_id = "feature.cylinder"
    registry = CommandRegistry()
    registry.register(
        CommandSpec(
            command_id,
            1,
            "cylinder v1",
            "圆柱 v1",
            {
                "type": "object",
                "properties": {
                    "radius": {"type": "number"},
                    "height": {"type": "number"},
                },
                "required": ["radius", "height"],
                "additionalProperties": False,
            },
            CliSyntax(("cylinder",)),
        )
    )
    registry.register(
        CommandSpec(
            command_id,
            2,
            "cylinder v2",
            "圆柱 v2",
            {
                "type": "object",
                "properties": {
                    "radius_mm": {"type": "number"},
                    "height_mm": {"type": "number"},
                },
                "required": ["radius_mm", "height_mm"],
                "additionalProperties": False,
            },
            CliSyntax(("cylinder",)),
        )
    )
    handlers: dict[tuple[str, int], CommandHandler] = {
        (command_id, version): VersionMarkerHandler(command_id, version) for version in (1, 2)
    }
    original_kernel = FakeKernel()
    original = Document(registry)
    bus = CommandBus(original, registry, original_kernel, handlers)
    bus.execute(command_id, {"radius": 4.0, "height": 8.0}, version=1)
    bus.execute(command_id, {"radius_mm": 5.0, "height_mm": 9.0}, version=2)
    archive = tmp_path / "legacy.mc.json"
    save_document(original, archive)

    replay_kernel = FakeKernel()
    loaded = open_document(
        archive,
        registry=registry,
        kernel=replay_kernel,
        handlers=handlers,
    )

    assert [command.version for command in loaded.document.commands] == [1, 2]
    assert replay_kernel.applied == [
        (command_id, {"radius": 4.0, "height": 8.0, "handler_version": 1}),
        (command_id, {"radius_mm": 5.0, "height_mm": 9.0, "handler_version": 2}),
    ]


def test_archive_missing_command_version_is_explicit(tmp_path: Path) -> None:
    path = tmp_path / "a.mc.json"
    seed_archive(path)

    def remove_version(data: dict[str, object]) -> None:
        commands = cast("list[object]", data["commands"])
        del cast("dict[str, object]", commands[0])["version"]

    reg, handlers, fake = make_assembly()
    with pytest.raises(ValidationError, match="missing command field 'version'"):
        open_document(tamper(path, remove_version), registry=reg, kernel=fake, handlers=handlers)
    assert fake.applied == []


def test_open_unregistered_command_id_rejected(tmp_path: Path) -> None:
    path = tmp_path / "a.mc.json"
    seed_archive(path)

    def rename_first(data: dict[str, object]) -> None:
        commands = cast("list[object]", data["commands"])
        cast("dict[str, object]", commands[0])["id"] = "demo.ghost"

    reg, handlers, fake = make_assembly()
    with pytest.raises(UnknownCommandError, match="demo.ghost"):
        open_document(tamper(path, rename_first), registry=reg, kernel=fake, handlers=handlers)


def test_open_second_command_geometry_failure_carries_ordinal(tmp_path: Path) -> None:
    path = tmp_path / "a.mc.json"
    seed_archive(path)
    reg, handlers, fake = make_assembly()
    fake.fail_when = lambda n, cid, p: GeometryBuildError("boom") if n >= 1 else None
    with pytest.raises(GeometryBuildError) as excinfo:
        open_document(path, registry=reg, kernel=fake, handlers=handlers)
    assert excinfo.value.ordinal == 1


def test_open_version_99_archive_version_error_fields(tmp_path: Path) -> None:
    path = tmp_path / "a.mc.json"
    seed_archive(path)
    reg, handlers, fake = make_assembly()
    with pytest.raises(ArchiveVersionError) as excinfo:
        open_document(
            tamper(path, lambda d: d.update(version=99)),
            registry=reg,
            kernel=fake,
            handlers=handlers,
        )
    assert excinfo.value.found == "99"
    assert excinfo.value.supported == 8


@pytest.mark.parametrize(
    ("fmt_value", "expected_found"),
    [("mycad.other", "mycad.other"), (None, "missing")],
)
def test_open_format_check_archive_version_error_fields(
    tmp_path: Path, fmt_value: str | None, expected_found: str
) -> None:
    path = tmp_path / "a.mc.json"
    seed_archive(path)

    def mutate(data: dict[str, object]) -> None:
        if fmt_value is None:
            del data["format"]
        else:
            data["format"] = fmt_value

    reg, handlers, fake = make_assembly()
    with pytest.raises(ArchiveVersionError) as excinfo:
        open_document(tamper(path, mutate), registry=reg, kernel=fake, handlers=handlers)
    assert excinfo.value.found == expected_found
    assert excinfo.value.supported == "mycad.document"


@pytest.mark.parametrize(
    "bad_selector",
    [{"surface": "cylinder", "axis": None}, {"surface": "plane", "axis": "+Z", "rank": None}],
)
def test_open_explicit_selector_null_rejected(
    tmp_path: Path, bad_selector: dict[str, object]
) -> None:
    path = tmp_path / "a.mc.json"
    seed_archive(path)

    def mutate(data: dict[str, object]) -> None:
        data["named_groups"] = [{"name": "g", "faces": [bad_selector], "edges": []}]

    reg, handlers, fake = make_assembly()
    with pytest.raises(ValidationError, match="null violates wire rule"):
        open_document(tamper(path, mutate), registry=reg, kernel=fake, handlers=handlers)


# -- round-trip matrix (appended batch; E402 suppressed by design) ------------
from mycad.core.groups import NamedGroup  # noqa: E402
from mycad.core.selectors import EdgeSelector, FaceSelector  # noqa: E402


def test_roundtrip_six_fields_and_amendments(tmp_path: Path) -> None:
    reg, handlers, fake = make_assembly()
    doc = Document(reg)
    bus = CommandBus(doc, reg, fake, handlers)
    bus.execute("feature.cylinder", {"radius": 1.0, "height": 2.0}, confirmed_by="cli-local")
    bus.execute("feature.cylinder", {"radius": 2.0, "height": 2.0})
    bus.edit_and_replay(0, {"radius": 3.0, "height": 2.0}, "cli-local", "fix radius")
    path = tmp_path / "rt.mc.json"
    save_document(doc, path)
    reg2, handlers2, fake2 = make_assembly()
    loaded = open_document(path, registry=reg2, kernel=fake2, handlers=handlers2)
    restored = loaded.document.commands
    assert len(restored) == 2
    for got, want in zip(restored, doc.commands, strict=True):
        assert got.id == want.id
        assert got.version == want.version
        assert got.params == want.params
        assert got.ordinal == want.ordinal
        assert got.timestamp_utc == want.timestamp_utc
        assert got.confirmed_by == want.confirmed_by
    assert restored[0].amendments == doc.commands[0].amendments
    first = restored[0].amendments[0]
    assert first.from_params["radius"] == 1.0
    assert first.actor == "cli-local"
    assert first.reason == "fix radius"
    assert restored[1].amendments == ()
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert "amendments" in cast("dict[str, object]", raw["commands"][0])
    assert "amendments" not in cast("dict[str, object]", raw["commands"][1])


def test_roundtrip_named_groups_mixed_selectors(tmp_path: Path) -> None:
    reg, _handlers, _fake = make_assembly()
    doc = Document(reg)
    plane = FaceSelector(surface="plane", axis="+Z", rank=1)
    cyl = FaceSelector(surface="cylinder")
    edge_plain = EdgeSelector(parent_faces=(plane,))
    edge_line = EdgeSelector(parent_faces=(cyl,), curve="line")
    doc.add_named_group(NamedGroup(name="g1", faces=(plane, cyl), edges=(edge_plain,)))
    doc.add_named_group(NamedGroup(name="g2", faces=(), edges=(edge_line,)))
    path = tmp_path / "g.mc.json"
    save_document(doc, path)
    reg2, handlers2, fake2 = make_assembly()
    loaded = open_document(path, registry=reg2, kernel=fake2, handlers=handlers2)
    groups = loaded.document.named_groups
    assert set(groups) == {"g1", "g2"}
    assert groups["g1"].faces == (plane, cyl)
    assert groups["g1"].edges == (edge_plain,)
    assert groups["g2"].faces == ()
    assert groups["g2"].edges == (edge_line,)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw_groups = cast("list[dict[str, object]]", raw["named_groups"])
    g2_raw = next(g for g in raw_groups if g["name"] == "g2")
    assert g2_raw["faces"] == []


def test_removed_group_disappears_from_archive(tmp_path: Path) -> None:
    doc = Document(demo_registry())
    doc.add_named_group(NamedGroup(name="temp", faces=(FaceSelector(surface="plane", axis="+Z"),)))
    path = tmp_path / "r.mc.json"
    save_document(doc, path)
    doc.remove_named_group("temp")
    save_document(doc, path)
    raw = path.read_text(encoding="utf-8")
    assert "temp" not in raw
    assert json.loads(raw)["named_groups"] == []


def test_cylinder_selector_without_axis_omitted_on_wire(tmp_path: Path) -> None:
    reg, handlers, fake = make_assembly()
    doc = Document(reg)
    bus = CommandBus(doc, reg, fake, handlers)
    bus.execute("demo.sel", {"surface": "cylinder", "axis": ""})
    assert doc.commands[0].params == {"surface": "cylinder"}
    path = tmp_path / "w.mc.json"
    save_document(doc, path)
    assert "axis" not in path.read_text(encoding="utf-8")
    reg2, handlers2, fake2 = make_assembly()
    loaded = open_document(path, registry=reg2, kernel=fake2, handlers=handlers2)
    assert loaded.document.commands[0].params == {"surface": "cylinder"}


def test_save_emits_saving_and_saved_once_with_path(tmp_path: Path) -> None:
    doc = Document(demo_registry())
    path = tmp_path / "s.mc.json"
    saving: list[object] = []
    saved: list[object] = []
    doc.events.subscribe("document_saving", saving.append)
    doc.events.subscribe("document_saved", saved.append)
    save_document(doc, path)
    assert saving == [{"path": str(path)}]
    assert saved == [{"path": str(path)}]


def test_save_missing_parent_oserror_and_no_tmp_residue(tmp_path: Path) -> None:
    doc = Document(demo_registry())
    with pytest.raises(OSError):
        save_document(doc, tmp_path / "nope" / "out.mc.json")
    good = tmp_path / "out.mc.json"
    save_document(doc, good)
    assert list(tmp_path.glob("*.tmp")) == []


def test_static_v1_archive_fixture_opens_and_preserves_audit_fields() -> None:
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "archives" / "v1_cylinders.mc.json"
    reg, handlers, fake = make_assembly()

    loaded = open_document(fixture, registry=reg, kernel=fake, handlers=handlers)

    commands = loaded.document.commands
    assert [
        (cmd.id, cmd.version, cmd.ordinal, cmd.timestamp_utc, cmd.confirmed_by) for cmd in commands
    ] == [
        ("feature.cylinder", 1, 0, "2026-01-01T00:00:00+00:00", "archive-fixture"),
        ("feature.cylinder", 1, 1, "2026-01-01T00:00:01+00:00", None),
    ]
    assert [cmd.params["radius"] for cmd in commands] == [5.0, 2.0]
    assert fake.applied == [
        (
            "feature.cylinder",
            {"radius": 5.0, "height": 2.0, "center": [0.0, 0.0, 0.0], "mode": "new"},
        ),
        (
            "feature.cylinder",
            {"radius": 2.0, "height": 2.0, "center": [0.0, 0.0, 0.0], "mode": "new"},
        ),
    ]


def test_replace_failure_preserves_archive_and_dirty_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core import persistence

    reg, handlers, fake = make_assembly()
    doc = Document(reg)
    bus = CommandBus(doc, reg, fake, handlers)
    bus.execute("feature.cylinder", {"radius": 1.0, "height": 2.0})
    path = tmp_path / "part.mc.json"
    save_document(doc, path)
    prior_bytes = path.read_bytes()
    doc.set_metadata("part_no", "changed")
    saved: list[object] = []
    doc.events.subscribe("document_saved", saved.append)

    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(persistence.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        save_document(doc, path)

    assert path.read_bytes() == prior_bytes
    assert doc.is_dirty
    assert saved == []
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.parametrize("failure_point", ["write", "flush"])
def test_temp_write_failure_preserves_archive_and_cleans_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_point: str
) -> None:
    from mycad.core import persistence

    reg, handlers, fake = make_assembly()
    doc = Document(reg)
    bus = CommandBus(doc, reg, fake, handlers)
    bus.execute("feature.cylinder", {"radius": 1.0, "height": 2.0})
    path = tmp_path / "part.mc.json"
    save_document(doc, path)
    prior_bytes = path.read_bytes()
    doc.set_metadata("part_no", "changed")
    saved: list[object] = []
    doc.events.subscribe("document_saved", saved.append)

    class FailingTemporaryFile:
        def __init__(self) -> None:
            self.path = tmp_path / "partial.tmp"
            self.name = str(self.path)
            self.handle: TextIO | None = None

        def __enter__(self) -> FailingTemporaryFile:
            self.handle = self.path.open("w", encoding="utf-8")
            return self

        def __exit__(
            self,
            _exc_type: object,
            _exc: object,
            _traceback: object,
        ) -> None:
            assert self.handle is not None
            self.handle.close()

        def write(self, value: str) -> int:
            assert self.handle is not None
            if failure_point == "write":
                self.handle.write(value[:1])
                raise OSError("simulated temp write failure")
            return self.handle.write(value)

        def flush(self) -> None:
            if failure_point == "flush":
                raise OSError("simulated temp flush failure")
            assert self.handle is not None
            self.handle.flush()

    def create_failing_file(*_args: object, **_kwargs: object) -> FailingTemporaryFile:
        return FailingTemporaryFile()

    monkeypatch.setattr(persistence.tempfile, "NamedTemporaryFile", create_failing_file)
    with pytest.raises(OSError, match=f"simulated temp {failure_point} failure"):
        save_document(doc, path)

    assert path.read_bytes() == prior_bytes
    assert doc.is_dirty
    assert saved == []
    assert list(tmp_path.glob("*.tmp")) == []
