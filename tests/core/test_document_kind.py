# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Independent drawing identity, write restrictions, and archive round trips."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

from mycad.commands.demo import demo_registry
from mycad.core.bus import CommandBus
from mycad.core.document import Document, DocumentType
from mycad.core.exceptions import ValidationError
from mycad.core.groups import NamedGroup
from mycad.core.handlers import HandlerContext
from mycad.core.measurements import MeasurementRequest, MeasurementResult
from mycad.core.persistence import open_document, save_document


class EmptyKernel:
    """Geometry double that records any accidental replay or write."""

    def __init__(self) -> None:
        self.applied: list[str] = []

    def reset(self) -> None:
        self.applied.clear()

    def apply(self, command_id: str, params: Mapping[str, object]) -> None:
        self.applied.append(command_id)

    def measure(self, request: MeasurementRequest) -> MeasurementResult:
        return MeasurementResult(
            value=None,
            unit="mm³",
            revision=request.revision,
            description="not available in test kernel",
            error="geometry is unavailable",
        )


class EchoHandler:
    command_id = "feature.cylinder"

    def handle(self, params: Mapping[str, object], ctx: HandlerContext) -> object | None:
        return None


def test_document_kind_is_explicit_and_drawing_requires_v3() -> None:
    registry = demo_registry()
    assert Document(registry).document_type == "part"
    assert Document(registry, document_type="drawing2d", archive_version=3).document_type == (
        "drawing2d"
    )
    with pytest.raises(ValidationError, match="archive_version 3"):
        Document(registry, document_type="drawing2d", archive_version=2)
    with pytest.raises(ValidationError, match="document_type"):
        Document(
            registry,
            document_type=cast("DocumentType", "assembly"),
            archive_version=3,
        )
    drawing = Document(registry, document_type="drawing2d", archive_version=3)
    with pytest.raises(ValidationError, match="3D named groups"):
        drawing.add_named_group(NamedGroup(name="solid", faces=(), edges=()))


def test_drawing_bus_rejects_every_command_outside_released_sketch_set() -> None:
    registry = demo_registry()
    kernel = EmptyKernel()
    document = Document(registry, document_type="drawing2d", archive_version=3)
    bus = CommandBus(
        document,
        registry,
        kernel,
        {"feature.cylinder": EchoHandler()},
    )

    with pytest.raises(ValidationError, match="feature.cylinder.*drawing2d"):
        bus.execute("feature.cylinder", {"radius": 2.0, "height": 4.0})
    assert document.commands == ()
    assert kernel.applied == []


def test_drawing_archive_saves_and_reopens_with_its_identity(tmp_path: Path) -> None:
    registry = demo_registry()
    path = tmp_path / "drawing.mc.json"
    drawing = Document(registry, document_type="drawing2d", archive_version=3)
    save_document(drawing, path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == 3
    assert payload["document_type"] == "drawing2d"

    kernel = EmptyKernel()
    loaded = open_document(path, registry=registry, kernel=kernel, handlers={})
    assert loaded.document.document_type == "drawing2d"
    assert loaded.document.archive_version == 3
    assert kernel.applied == []


def test_legacy_v2_archive_is_still_a_part_document(tmp_path: Path) -> None:
    registry = demo_registry()
    path = tmp_path / "legacy.mc.json"
    save_document(Document(registry, archive_version=2), path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == 2
    assert "document_type" not in payload

    loaded = open_document(path, registry=registry, kernel=EmptyKernel(), handlers={})
    assert loaded.document.document_type == "part"
    assert loaded.document.archive_version == 2


def test_v3_archive_rejects_solid_history_before_kernel_replay(tmp_path: Path) -> None:
    registry = demo_registry()
    path = tmp_path / "tampered.mc.json"
    save_document(Document(registry, document_type="drawing2d", archive_version=3), path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["commands"].append(
        {
            "id": "feature.cylinder",
            "version": 1,
            "params": {"radius": 1.0, "height": 1.0},
            "ordinal": 0,
            "timestamp_utc": "2026-10-25T00:00:00+00:00",
            "confirmed_by": None,
        }
    )
    path.write_text(json.dumps(payload), encoding="utf-8")
    kernel = EmptyKernel()

    with pytest.raises(ValidationError, match="drawing2d.*feature.cylinder"):
        open_document(
            path,
            registry=registry,
            kernel=kernel,
            handlers={"feature.cylinder": EchoHandler()},
        )
    assert kernel.applied == []
