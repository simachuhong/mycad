# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Core integration tests (T6d): real BuildKernel end-to-end scenarios."""

from __future__ import annotations

from mycad.commands.registry import CommandRegistry
from mycad.commands.spec import CliSyntax, CommandSpec
from mycad.core.bus import CommandBus
from mycad.core.document import Document
from mycad.core.handlers import BuiltinModelingHandler, CommandHandler
from mycad.geom.kernel import BuildKernel

_DEFS: dict[str, object] = {
    "Mode": {"type": "string", "enum": ["new", "add", "cut"], "default": "new"},
    "Center3": {
        "type": "array",
        "items": {"type": "number"},
        "minItems": 3,
        "maxItems": 3,
        "default": [0.0, 0.0, 0.0],
    },
    "Positive": {"type": "number", "exclusiveMinimum": 0.0},
    "FaceSelector": {
        "type": "object",
        "required": ["surface", "axis"],
        "additionalProperties": False,
        "properties": {
            "surface": {"const": "plane"},
            "axis": {"type": "string", "enum": ["+X", "-X", "+Y", "-Y", "+Z", "-Z"]},
            "rank": {"type": "integer", "minimum": 0},
        },
    },
    "EdgeSelector": {
        "type": "object",
        "required": ["parent_faces"],
        "additionalProperties": False,
        "properties": {
            "parent_faces": {
                "type": "array",
                "items": {"$ref": "#/$defs/FaceSelector"},
                "minItems": 1,
            },
            "curve": {"type": "string", "enum": ["line", "circle", ""]},
        },
    },
}

_BOX_SCHEMA: dict[str, object] = {
    "type": "object",
    "required": ["size_x", "size_y", "size_z"],
    "additionalProperties": False,
    "properties": {
        "size_x": {"$ref": "#/$defs/Positive"},
        "size_y": {"$ref": "#/$defs/Positive"},
        "size_z": {"$ref": "#/$defs/Positive"},
        "center": {"$ref": "#/$defs/Center3"},
        "mode": {"$ref": "#/$defs/Mode"},
    },
}

_CYLINDER_SCHEMA: dict[str, object] = {
    "type": "object",
    "required": ["radius", "height"],
    "additionalProperties": False,
    "properties": {
        "radius": {"$ref": "#/$defs/Positive"},
        "height": {"$ref": "#/$defs/Positive"},
        "center": {"$ref": "#/$defs/Center3"},
        "mode": {"$ref": "#/$defs/Mode"},
    },
}

_FILLET_SCHEMA: dict[str, object] = {
    "type": "object",
    "required": ["edges", "radius"],
    "additionalProperties": False,
    "properties": {
        "edges": {"type": "array", "items": {"$ref": "#/$defs/EdgeSelector"}, "minItems": 1},
        "radius": {"$ref": "#/$defs/Positive"},
    },
}

_COMMAND_IDS = ("feature.box", "feature.cylinder", "modify.fillet")


def _spec(cid: str, label: str, schema: dict[str, object], verb: str) -> CommandSpec:
    """Test-local spec factory (summary_en is the id itself)."""
    return CommandSpec(cid, 1, cid, label, schema, CliSyntax((verb,)))


def make_assembly() -> tuple[CommandRegistry, dict[str, CommandHandler], BuildKernel]:
    """Fresh registry/handlers/real kernel wired with the three self-built specs."""
    reg = CommandRegistry(schema_defs=_DEFS)
    reg.register(_spec("feature.box", "长方体", _BOX_SCHEMA, "box"))
    reg.register(_spec("feature.cylinder", "圆柱体", _CYLINDER_SCHEMA, "cylinder"))
    reg.register(_spec("modify.fillet", "圆角", _FILLET_SCHEMA, "fillet"))
    kernel = BuildKernel()
    handlers: dict[str, CommandHandler] = {cid: BuiltinModelingHandler(cid) for cid in _COMMAND_IDS}
    return reg, handlers, kernel


def make_bus() -> tuple[CommandBus, Document, BuildKernel]:
    """Bus + document + real kernel (fresh assembly per call)."""
    reg, handlers, kernel = make_assembly()
    doc = Document(reg)
    return CommandBus(doc, reg, kernel, handlers), doc, kernel


# -- scenarios ①/② (appended batch; E402 suppressed by design) ----------------
import math  # noqa: E402

import pytest  # noqa: E402

BOX_PARAMS: dict[str, object] = {"size_x": 10.0, "size_y": 20.0, "size_z": 30.0}
CYL1: dict[str, object] = {"radius": 2.0, "height": 4.0, "center": [100.0, 0.0, 0.0], "mode": "add"}
CYL2: dict[str, object] = {"radius": 3.0, "height": 6.0, "center": [200.0, 0.0, 0.0], "mode": "add"}
_COMBINED_VOLUME = 10.0 * 20.0 * 30.0 + math.pi * 2.0**2 * 4.0 + math.pi * 3.0**2 * 6.0


def test_execute_undo_redo_volumes_with_real_kernel() -> None:
    bus, doc, kernel = make_bus()
    bus.execute("feature.box", BOX_PARAMS, confirmed_by="cli-local")
    bus.execute("feature.cylinder", CYL1, confirmed_by="cli-local")
    bus.execute("feature.cylinder", CYL2, confirmed_by="cli-local")
    assert kernel.mass_properties().volume == pytest.approx(_COMBINED_VOLUME, rel=1e-6)
    bus.undo(2)
    assert kernel.mass_properties().volume == pytest.approx(6000.0, rel=1e-6)
    bus.redo(2)
    assert kernel.mass_properties().volume == pytest.approx(_COMBINED_VOLUME, rel=1e-6)
    assert [c.id for c in doc.commands] == [
        "feature.box",
        "feature.cylinder",
        "feature.cylinder",
    ]


def test_edit_and_replay_cylinder_radius_rebuilds_volume() -> None:
    bus, doc, kernel = make_bus()
    bus.execute("feature.cylinder", {"radius": 2.0, "height": 10.0})
    bus.edit_and_replay(0, {"radius": 3.0, "height": 10.0}, "cli-local", "bigger radius")
    assert kernel.mass_properties().volume == pytest.approx(math.pi * 3.0**2 * 10.0, rel=1e-6)
    assert len(doc.commands) == 1
    assert doc.commands[0].params["radius"] == 3.0
    assert len(doc.commands[0].amendments) == 1


# -- scenarios ③/④/⑤ (appended batch; E402 suppressed by design) --------------
import time  # noqa: E402
from pathlib import Path  # noqa: E402

from mycad.core.exceptions import BatchRollbackError  # noqa: E402
from mycad.core.persistence import open_document, save_document  # noqa: E402
from mycad.core.plan import Plan, PlannedCommand  # noqa: E402

_BOX10: dict[str, object] = {"size_x": 10.0, "size_y": 10.0, "size_z": 10.0}


def test_qa_happy_path_save_open_roundtrip(tmp_path: Path) -> None:
    bus, doc, kernel = make_bus()
    bus.execute("feature.box", BOX_PARAMS, confirmed_by="cli-local")
    bus.execute("feature.cylinder", CYL1, confirmed_by="cli-local")
    bus.execute("feature.cylinder", CYL2, confirmed_by="cli-local")
    bus.undo(2)
    assert kernel.mass_properties().volume == pytest.approx(6000.0, rel=1e-6)
    bus.redo(2)
    out = tmp_path / "out.mc.json"
    save_document(doc, out)
    reg2, handlers2, kernel2 = make_assembly()
    loaded = open_document(out, registry=reg2, kernel=kernel2, handlers=handlers2)
    assert kernel2.mass_properties().volume == pytest.approx(_COMBINED_VOLUME, rel=1e-6)
    restored = loaded.document.commands
    assert len(restored) == 3
    for got, want in zip(restored, doc.commands, strict=True):
        assert got.id == want.id
        assert got.version == want.version
        assert got.params == want.params
        assert got.ordinal == want.ordinal
        assert got.timestamp_utc == want.timestamp_utc
        assert got.confirmed_by == "cli-local"


def _cyl_step(radius: float, height: float, center: list[float]) -> PlannedCommand:
    return PlannedCommand(
        id="feature.cylinder",
        version=1,
        summary_en="cylinder",
        affected_object="cylinder_body",
        params={"radius": radius, "height": height, "mode": "add", "center": center},
    )


def _fillet_step(radius: float) -> PlannedCommand:
    return PlannedCommand(
        id="modify.fillet",
        version=1,
        summary_en="fillet",
        affected_object="edge",
        params={
            "edges": [{"parent_faces": [{"surface": "plane", "axis": "+Z"}]}],
            "radius": radius,
        },
    )


def test_batch_validate_failure_rolls_back_with_real_kernel() -> None:
    bus, doc, kernel = make_bus()
    bus.execute("feature.box", BOX_PARAMS, confirmed_by="cli-local")
    plan = Plan(
        steps=[_cyl_step(2.0, 4.0, [100.0, 0.0, 0.0]), _cyl_step(-1.0, 4.0, [100.0, 0.0, 0.0])]
    )
    plan.confirm("cli-local")
    with pytest.raises(BatchRollbackError) as excinfo:
        bus.execute_batch(plan)
    err = excinfo.value
    assert err.failed_ordinal == 1
    assert err.failed_command_id == "feature.cylinder"
    assert "radius" in err.reason
    assert err.executed_ids == ("feature.cylinder",)
    assert [c.id for c in doc.commands] == ["feature.box"]
    assert kernel.mass_properties().volume == pytest.approx(6000.0, rel=1e-6)
    assert plan.status == "failed"


def test_batch_geometry_failure_rolls_back_with_real_kernel() -> None:
    bus, doc, kernel = make_bus()
    bus.execute("feature.box", _BOX10, confirmed_by="cli-local")
    plan = Plan(
        steps=[
            _cyl_step(2.0, 4.0, [100.0, 0.0, 0.0]),
            _cyl_step(3.0, 6.0, [200.0, 0.0, 0.0]),
            _fillet_step(999.0),
        ]
    )
    plan.confirm("cli-local")
    with pytest.raises(BatchRollbackError) as excinfo:
        bus.execute_batch(plan)
    err = excinfo.value
    assert err.failed_ordinal == 2
    assert err.failed_command_id == "modify.fillet"
    assert err.executed_ids == ("feature.cylinder", "feature.cylinder")
    assert [c.id for c in doc.commands] == ["feature.box"]
    assert kernel.mass_properties().volume == pytest.approx(1000.0, rel=1e-6)
    assert plan.status == "failed"


def test_open_replay_performance_gate(tmp_path: Path) -> None:
    bus, doc, _kernel = make_bus()
    bus.execute("feature.box", BOX_PARAMS, confirmed_by="cli-local")
    for index in range(9):
        center = [50.0 + 10.0 * index, 0.0, 0.0]
        bus.execute(
            "feature.cylinder",
            {"radius": 1.0, "height": 2.0, "mode": "add", "center": center},
            confirmed_by="cli-local",
        )
    path = tmp_path / "perf.mc.json"
    save_document(doc, path)
    durations: list[float] = []
    for _ in range(10):
        reg, handlers, kernel = make_assembly()
        start = time.perf_counter()
        open_document(path, registry=reg, kernel=kernel, handlers=handlers)
        durations.append(time.perf_counter() - start)
    print(f"replay wall-clock ms: {[round(d * 1000, 1) for d in durations]}")
    assert len(durations) == 10
    worst = max(durations)
    assert worst < 1.0, f"slowest replay {worst * 1000:.1f}ms (NF-04 gate: <1000ms)"
