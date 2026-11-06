# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Binding wire/version checks do not depend on a CAD backend."""

from __future__ import annotations

from typing import cast

import pytest

from mycad.builtin_commands import BUILTIN_COMMAND_SPECS, COMMAND_SCHEMA_DEFS
from mycad.commands.registry import CommandRegistry
from mycad.commands.validation import validate_params
from mycad.core.bound_refs import BoundFaceRef
from mycad.core.bus import CommandBus
from mycad.core.document import Document
from mycad.core.exceptions import TopologyReferenceError, ValidationError
from mycad.core.handlers import BuiltinModelingHandler
from mycad.core.persistence import document_payload, load_document_payload
from tests.core.test_persistence import FakeKernel


def registry() -> CommandRegistry:
    result = CommandRegistry(COMMAND_SCHEMA_DEFS)
    for spec in BUILTIN_COMMAND_SPECS:
        result.register(spec)
    return result


def params() -> dict[str, object]:
    return {
        "target_face": BoundFaceRef("a" * 32, "box.+Z").to_mapping(),
        "position": {"kind": "local", "uv_mm": [2, 3]},
        "diameter": 2,
        "depth": {"kind": "through_all"},
    }


@pytest.mark.parametrize("fault", ["uuid", "role", "rank"])
def test_invalid_binding_does_not_become_a_query(fault: str) -> None:
    wire = BoundFaceRef("a" * 32, "box.+Z").to_mapping()
    wire[{"uuid": "source_instance_id", "role": "role", "rank": "rank"}[fault]] = {
        "uuid": "invalid",
        "role": "max-face",
        "rank": 0,
    }[fault]
    with pytest.raises(ValidationError):
        BoundFaceRef.from_mapping(wire)


def test_old_versions_reject_binding_and_v3_rejects_local_query() -> None:
    reg = registry()
    for version in (1, 2):
        with pytest.raises(ValidationError):
            validate_params(reg.get("feature.hole", version), params(), defs=reg.schema_defs)
    wrong = params()
    wrong["target_face"] = {"surface": "plane", "axis": "+Z"}
    with pytest.raises(ValidationError):
        validate_params(reg.get("feature.hole", 3), wrong, defs=reg.schema_defs)


def test_legacy_kernel_cannot_silently_execute_binding() -> None:
    reg = registry()
    doc, kernel = Document(reg), FakeKernel()
    handlers = {
        (spec.id, spec.version): BuiltinModelingHandler(spec.id, spec.version)
        for spec in BUILTIN_COMMAND_SPECS
    }
    bus = CommandBus(doc, reg, kernel, handlers)
    bus.apply_identity_upgrade(bus.prepare_identity_upgrade())
    with pytest.raises(TopologyReferenceError) as error:
        bus.execute("feature.hole", params())
    assert error.value.reason == "unsupported-kernel"
    assert error.value.ordinal == 0
    assert kernel.applied == []
    assert doc.commands == ()


def test_old_format_bound_command_is_rejected_before_kernel_reset() -> None:
    reg = registry()
    doc, kernel = Document(reg), FakeKernel()
    handlers = {
        (spec.id, spec.version): BuiltinModelingHandler(spec.id, spec.version)
        for spec in BUILTIN_COMMAND_SPECS
    }
    bus = CommandBus(doc, reg, kernel, handlers)
    bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    payload = document_payload(doc)
    entry = cast("list[dict[str, object]]", payload["commands"])[0]
    entry.update(id="feature.hole", version=3, params=params())
    before = list(kernel.applied)
    with pytest.raises(ValidationError, match="v5"):
        load_document_payload(payload, registry=reg, kernel=kernel, handlers=handlers)
    assert kernel.applied == before


@pytest.mark.parametrize("loading", [False, True])
def test_malformed_binding_is_located_before_kernel_work(loading: bool) -> None:
    reg = registry()
    doc, kernel = Document(reg), FakeKernel()
    handlers = {
        (spec.id, spec.version): BuiltinModelingHandler(spec.id, spec.version)
        for spec in BUILTIN_COMMAND_SPECS
    }
    bus = CommandBus(doc, reg, kernel, handlers)
    bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    bus.apply_identity_upgrade(bus.prepare_identity_upgrade())
    invalid = params()
    invalid["target_face"] = {
        "kind": "bound_face",
        "source_instance_id": "z" * 32,
        "role": "box.+Z",
    }
    before = list(kernel.applied)
    with pytest.raises(TopologyReferenceError) as error:
        if loading:
            payload = document_payload(doc)
            entry = cast("list[dict[str, object]]", payload["commands"])[0]
            entry.update(id="feature.hole", version=3, params=invalid)
            load_document_payload(payload, registry=reg, kernel=kernel, handlers=handlers)
        else:
            bus.execute("feature.hole", invalid)
    assert error.value.command_id == "feature.hole"
    assert error.value.ordinal == (0 if loading else 1)
    assert error.value.parameter_path == "target_face"
    assert error.value.reason == "invalid-reference"
    assert kernel.applied == before
    assert len(doc.commands) == 1
