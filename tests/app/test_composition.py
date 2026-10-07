# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Composition-root tests (T7c): build_app wiring and the document factory."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from mycad.app import AppServices, build_app, new_document
from mycad.core.exceptions import UnknownCommandError
from mycad.core.persistence import LoadedDocument

EIGHT_P0_IDS: list[str] = [
    "feature.box",
    "feature.cylinder",
    "feature.extrude",
    "feature.hole",
    "feature.hole_pattern",
    "feature.revolve",
    "modify.boolean_cut",
    "modify.fillet",
]


def _registered_ids(services: AppServices) -> list[str]:
    return [spec.id for group in services.registry.list_by_category().values() for spec in group]


def test_build_app_registers_exactly_the_eight_p0_ids() -> None:
    services = build_app(discoverers=[])
    assert sorted(_registered_ids(services)) == EIGHT_P0_IDS


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
