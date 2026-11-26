# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Bus, archive and document-gating gaps from the text acceptance matrix."""

from dataclasses import replace
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest

from mycad import app
from mycad.core.document import Document
from mycad.core.document_kinds import DocumentKind
from mycad.core.drawing_text import DrawingText, TextStyle, TextStyleTable
from mycad.core.exceptions import ValidationError
from mycad.core.persistence import save_document
from mycad.core.sketch import RectangleEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_layers import SketchLayer


@pytest.mark.parametrize("kind", ["part", "drawing"])
@pytest.mark.parametrize(
    "command",
    [
        "drawing.text.add",
        "drawing.text.update",
        "drawing.text.remove",
        "drawing.text.batch",
        "drawing.text_styles.set",
    ],
)
def test_all_text_commands_reject_non_sketch_documents(kind: str, command: str) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind=cast("DocumentKind", kind))
    item = DrawingText(uuid4().hex, "A", (0, 0))
    params: dict[str, object] = {
        "drawing.text.add": item.to_mapping(),
        "drawing.text.update": item.to_mapping(),
        "drawing.text.remove": {"text_id": item.text_id},
        "drawing.text.batch": {"add": [item.to_mapping()]},
        "drawing.text_styles.set": TextStyleTable().to_mapping(),
    }
    with pytest.raises(ValidationError):
        loaded.bus.execute(command, cast("dict[str, object]", params[command]), "local")
    assert not loaded.document.commands
    assert not services.kernel.drawing_texts


def test_five_commands_audit_fields_survive_save_and_replay(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    style = TextStyle("cn", "中文", "Missing font", height_mm=4, width_factor=0.8)
    styles = TextStyleTable((TextStyle(), style), "cn")
    first = DrawingText(uuid4().hex, "中文 ABC", (10, 20), style_id="cn", rotation_deg=30)
    second = DrawingText(
        uuid4().hex,
        "第一行\n\n第三行",
        (3, 4),
        kind="mtext",
        style_id="cn",
        align="middle_right",
        box_width_mm=40,
        line_spacing=1.5,
    )
    sequence = (
        ("drawing.text_styles.set", styles.to_mapping()),
        ("drawing.text.add", first.to_mapping()),
        ("drawing.text.update", replace(first, text="新内容").to_mapping()),
        ("drawing.text.batch", {"add": [second.to_mapping()]}),
        ("drawing.text.remove", {"text_id": first.text_id}),
    )
    for command, params in sequence:
        loaded.bus.execute(command, params, "qa-local")
    records = loaded.document.commands
    assert [record.id for record in records] == [command for command, _params in sequence]
    assert [record.version for record in records] == [1] * 5
    assert [record.params for record in records] == [params for _command, params in sequence]
    assert [record.ordinal for record in records] == list(range(5))
    assert all(record.timestamp_utc and record.confirmed_by == "qa-local" for record in records)
    assert loaded.document.archive_version >= 4
    path = tmp_path / "audit.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert reopened.document.commands == records
    assert services.kernel.drawing_texts == (second,)
    assert services.kernel.drawing_text_styles == styles
    reopened.bus.undo()
    assert services.kernel.drawing_texts == (replace(first, text="新内容"), second)
    reopened.bus.redo()
    assert services.kernel.drawing_texts == (second,)


def test_pre_text_v3_drawing_reopens_and_upgrades_on_text_edit(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    legacy = Document(services.registry, archive_version=3, document_type="drawing2d")
    path = tmp_path / "before-text.my2d"
    save_document(legacy, path)
    loaded = app.open_app_document(services, path)
    assert loaded.document.document_kind == "sketch"
    assert loaded.document.archive_version == 3
    assert not services.kernel.drawing_texts
    text = DrawingText(uuid4().hex, "New text", (1, 2))
    loaded.bus.execute("drawing.text.add", text.to_mapping(), "local")
    assert loaded.document.archive_version >= 4
    save_document(loaded.document, path)
    app.open_app_document(services, path)
    assert services.kernel.drawing_texts == (text,)


def test_failed_duplicate_and_missing_style_preserve_document_and_redo() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    item = DrawingText(uuid4().hex, "A", (0, 0))
    moved = replace(item, position_mm=(4, 5))
    loaded.bus.execute("drawing.text.add", item.to_mapping(), "local")
    loaded.bus.execute("drawing.text.update", moved.to_mapping(), "local")
    loaded.bus.undo()
    before = (
        loaded.document.commands,
        services.kernel.drawing_texts,
        services.kernel.drawing_text_styles,
        services.kernel.drawing_layers,
        services.kernel.sketches,
        services.kernel.drawing_rasters,
    )
    invalid = (
        ("drawing.text.add", item.to_mapping()),
        ("drawing.text.update", replace(item, text_id=uuid4().hex).to_mapping()),
        ("drawing.text.batch", {"update": [replace(item, style_id="missing").to_mapping()]}),
    )
    for command, params in invalid:
        with pytest.raises(ValidationError):
            loaded.bus.execute(command, params, "local")
        assert (
            loaded.document.commands,
            services.kernel.drawing_texts,
            services.kernel.drawing_text_styles,
            services.kernel.drawing_layers,
            services.kernel.sketches,
            services.kernel.drawing_rasters,
        ) == before
    loaded.bus.redo()
    assert services.kernel.drawing_texts == (moved,)


@pytest.mark.parametrize("attribute", ["locked", "frozen"])
@pytest.mark.parametrize("action", ["add", "update", "remove"])
def test_locked_and_frozen_layer_reject_all_text_edits(attribute: str, action: str) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    layers = services.kernel.drawing_layers.add(SketchLayer("TEXT"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    item = DrawingText(uuid4().hex, "A", (0, 0), layer_name="TEXT")
    loaded.bus.execute("drawing.text.add", item.to_mapping(), "local")
    changed = layers.replace(replace(layers.get("TEXT"), **{attribute: True}))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": changed.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    before = (
        loaded.document.commands,
        services.kernel.drawing_texts,
        services.kernel.drawing_text_styles,
        services.kernel.drawing_layers,
    )
    if action == "add":
        params = replace(item, text_id=uuid4().hex).to_mapping()
    elif action == "update":
        params = replace(item, text="changed").to_mapping()
    else:
        params = {"text_id": item.text_id}
    with pytest.raises(ValidationError):
        loaded.bus.execute(f"drawing.text.{action}", params, "local")
    assert (
        loaded.document.commands,
        services.kernel.drawing_texts,
        services.kernel.drawing_text_styles,
        services.kernel.drawing_layers,
    ) == before


def test_text_does_not_change_sketch_constraints_or_closed_regions() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (20, 10))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    before_sketches = services.kernel.sketches
    before_regions = services.kernel.sketch_region_data(before_sketches[0])
    assert before_regions
    text = DrawingText(uuid4().hex, "ABC", (5, 5))
    loaded.bus.execute("drawing.text.add", text.to_mapping(), "local")
    assert services.kernel.sketches == before_sketches
    assert services.kernel.sketches[0].constraints == sketch.constraints
    assert services.kernel.sketch_region_data(services.kernel.sketches[0]) == before_regions


def test_archive_reopens_all_explicit_text_fields_and_missing_font(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    layers = services.kernel.drawing_layers.add(SketchLayer("TEXT"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    style = TextStyle("cn", "技术", "Missing Family", "Italic", "missing.ttf", 4, 0.8)
    styles = TextStyleTable((TextStyle(), style), "cn")
    texts = (
        DrawingText(
            uuid4().hex,
            "中文 ABC ⌀ ± °",
            (10, 20),
            style_id="cn",
            height_mm=4,
            width_factor=0.8,
            rotation_deg=30,
            align="top_center",
            layer_name="TEXT",
        ),
        DrawingText(
            uuid4().hex,
            "第一行\n\n第三行",
            (5, 7),
            kind="mtext",
            style_id="cn",
            height_mm=6,
            width_factor=1.2,
            rotation_deg=90,
            align="bottom_right",
            box_width_mm=40,
            line_spacing=1.5,
            layer_name="TEXT",
        ),
    )
    loaded.bus.execute(
        "drawing.text.batch",
        {"styles": styles.to_mapping(), "add": [text.to_mapping() for text in texts]},
        "local",
    )
    path = tmp_path / "fields.my2d"
    save_document(loaded.document, path)
    app.open_app_document(services, path)
    assert services.kernel.drawing_texts == texts
    assert services.kernel.drawing_text_styles == styles
    assert services.kernel.drawing_layers.get("TEXT") == layers.get("TEXT")
