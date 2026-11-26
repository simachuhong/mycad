# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Drawing text and styles are atomic replayable document operations."""

from dataclasses import replace
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest

from mycad import app
from mycad.core.document_kinds import DocumentKind
from mycad.core.drawing_text import DrawingText, TextStyle, TextStyleTable
from mycad.core.exceptions import ValidationError
from mycad.core.persistence import save_document
from mycad.core.sketch_layers import SketchLayer, SketchLayerTable


def test_text_batch_styles_undo_redo_and_persistence(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    style = TextStyle("cn", "中文", "Missing font", height_mm=5)
    table = TextStyleTable((TextStyle(), style), "cn")
    text = DrawingText(uuid4().hex, "说明\n第二行", (3, 4), kind="mtext", style_id="cn")
    loaded.bus.execute(
        "drawing.text.batch", {"add": [text.to_mapping()], "styles": table.to_mapping()}, "local"
    )
    assert services.kernel.drawing_texts == (text,)
    assert services.kernel.drawing_text_styles == table
    loaded.bus.undo()
    assert not services.kernel.drawing_texts
    assert services.kernel.drawing_text_styles == TextStyleTable()
    loaded.bus.redo()
    moved = replace(text, position_mm=(12, 13))
    loaded.bus.execute("drawing.text.update", moved.to_mapping(), "local")
    path = tmp_path / "text.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_texts == (moved,)
    assert services.kernel.drawing_text_styles == table
    reopened.bus.execute("drawing.text.remove", {"text_id": text.text_id}, "local")
    assert not services.kernel.drawing_texts
    reopened.bus.undo()
    assert services.kernel.drawing_texts == (moved,)


def test_batch_failure_never_publishes_partial_text_or_styles() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    text = DrawingText(uuid4().hex, "A", (0, 0))
    loaded.bus.execute("drawing.text.add", text.to_mapping(), "local")
    before = loaded.document.command_count
    changed_styles = TextStyleTable((replace(TextStyle(), height_mm=10),))
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.text.batch",
            {
                "update": [replace(text, text="B").to_mapping()],
                "remove": [uuid4().hex],
                "styles": changed_styles.to_mapping(),
            },
            "local",
        )
    assert services.kernel.drawing_texts == (text,)
    assert services.kernel.drawing_text_styles == TextStyleTable()
    assert loaded.document.command_count == before
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.text.batch", {"remove": [text.text_id, text.text_id]}, "local")
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.text_styles.set",
            TextStyleTable((TextStyle("x", "other"),), "x").to_mapping(),
            "local",
        )
    assert services.kernel.drawing_texts == (text,)


def test_layer_deletion_and_locked_edit_are_protected() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    layers = services.kernel.drawing_layers.add(SketchLayer("文字"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    text = DrawingText(uuid4().hex, "A", (0, 0), layer_name="文字")
    loaded.bus.execute("drawing.text.add", text.to_mapping(), "local")
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.layers.set",
            {"layers": SketchLayerTable().to_mapping(), "dimension_layer": "0"},
            "local",
        )
    locked = replace(
        layers,
        layers=tuple(
            replace(layer, locked=True) if layer.name == "文字" else layer
            for layer in layers.layers
        ),
    )
    loaded.bus.execute(
        "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.text.remove", {"text_id": text.text_id}, "local")
    assert services.kernel.drawing_texts == (text,)


@pytest.mark.parametrize("kind", ["part", "drawing"])
def test_text_only_allowed_in_sketch_documents(kind: str) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind=cast("DocumentKind", kind))
    text = DrawingText(uuid4().hex, "A", (0, 0))
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.text.add", text.to_mapping(), "local")
    assert not loaded.document.commands


def test_sketch_revision_retains_text_on_custom_layer(tmp_path: Path) -> None:
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    layers = services.kernel.drawing_layers.add(SketchLayer("文字"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    text = DrawingText(uuid4().hex, "保留", (0, 0), layer_name="文字")
    loaded.bus.execute("drawing.text.add", text.to_mapping(), "local")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), layers=layers)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    moved = replace(sketch, entities=(replace(line, start_mm=(2, 3), end_mm=(12, 3)),))
    state = moved.to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
        version=52,
    )
    assert services.kernel.drawing_texts == (text,)
    assert services.kernel.sketches == (moved,)
    path = tmp_path / "revised.my2d"
    save_document(loaded.document, path)
    app.open_app_document(services, path)
    assert services.kernel.drawing_texts == (text,)
