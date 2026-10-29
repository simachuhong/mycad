# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Composition-root tests (T7c): build_app wiring and the document factory."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from uuid import uuid4

import pytest

from mycad.app import AppServices, build_app, new_document, open_app_document
from mycad.core.exceptions import UnknownCommandError
from mycad.core.persistence import LoadedDocument, save_document
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

BUILTIN_IDS: list[str] = [
    "drawing.annotation.create",
    "drawing.annotation.delete",
    "drawing.annotation.update",
    "drawing.layers.set",
    "drawing.note.create",
    "drawing.note.delete",
    "drawing.note.update",
    "drawing.sheet.create",
    "drawing.sheet.delete",
    "drawing.sheet.update",
    "drawing.view.create",
    "drawing.view.delete",
    "drawing.view.update",
    "feature.box",
    "feature.cylinder",
    "feature.extrude",
    "feature.hole",
    "feature.hole_pattern",
    "feature.revolve",
    "modify.body_pattern",
    "modify.body_transform",
    "modify.boolean_bodies",
    "modify.boolean_cut",
    "modify.boolean_intersect",
    "modify.chamfer",
    "modify.fillet",
    "reference.attach",
    "reference.detach",
    "reference.update",
    "sketch.constraint.add",
    "sketch.constraint.update",
    "sketch.create",
]


def _registered_ids(services: AppServices) -> list[str]:
    return [spec.id for group in services.registry.list_by_category().values() for spec in group]


def test_build_app_registers_p0_and_released_p2_builtin_ids() -> None:
    services = build_app(discoverers=[])
    assert sorted(_registered_ids(services)) == BUILTIN_IDS


def test_app_services_field_layout_is_pinned() -> None:
    names = tuple(field.name for field in dataclasses.fields(AppServices))
    assert names == ("registry", "kernel", "formats", "plugins")


def test_services_members_are_wired_and_step_resolution_smokes() -> None:
    services = build_app(discoverers=[])
    assert services.kernel is not None
    assert services.formats is not None
    assert services.plugins is not None
    assert services.plugins.discovered_plugins == ()
    provider = services.formats.resolve(Path("flange.step"))
    assert provider.name == "STEP"
    assert services.formats.resolve(Path("drawing.dxf")).name == "DXF sketch subset"


def test_new_document_returns_fresh_loaded_document() -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    assert isinstance(loaded, LoadedDocument)
    assert loaded.document.metadata == {
        "part_no": "",
        "revision": "",
        "material": "",
        "source": "local",
    }
    assert loaded.document.commands == ()


def test_new_independent_drawing_has_explicit_v3_identity() -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services, document_type="drawing2d")
    assert loaded.document.document_type == "drawing2d"
    assert loaded.document.archive_version == 3
    assert loaded.document.commands == ()
    assert services.kernel.mass_properties().solid_count == 0


def test_part_with_a_sketch_stays_a_part_in_v2_archive(tmp_path: Path) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    sketch_id = uuid4().hex
    loaded.bus.execute(
        "sketch.create",
        Sketch(
            sketch_id=sketch_id,
            frame=WorkPlaneFrame.xy(),
            entities=(LineEntity(uuid4().hex, (0.0, 0.0), (8.0, 0.0)),),
        ).to_mapping(),
        confirmed_by="test",
    )
    path = tmp_path / "part-with-sketch.mc.json"
    save_document(loaded.document, path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == 2
    assert "document_type" not in payload
    reopened = open_app_document(services, path)
    assert reopened.document.document_type == "part"
    assert reopened.document.commands[0].params["sketch_id"] == sketch_id


def test_new_document_resets_shared_kernel_between_documents() -> None:
    services = build_app(discoverers=[])
    doc1 = new_document(services)
    doc1.bus.execute("feature.box", {"size_x": 10.0, "size_y": 20.0, "size_z": 30.0})
    assert services.kernel.mass_properties().solid_count == 1
    doc2 = new_document(services)
    mass = services.kernel.mass_properties()
    assert mass.solid_count == 0
    assert mass.volume == 0.0
    assert doc2.document.commands == ()


def test_unknown_command_id_raises_through_the_bus() -> None:
    services = build_app(discoverers=[])
    doc = new_document(services)
    with pytest.raises(UnknownCommandError):
        doc.bus.execute("feature.sweep", {"size_x": 1.0})
