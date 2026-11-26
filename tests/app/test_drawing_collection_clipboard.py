# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Collection clipboard identity and transaction behavior."""

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest

from mycad import app
from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
from mycad.core.drawing_text import DrawingText
from mycad.core.replay_proposal import ReplayAppend
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.ui.drawing_collection_session import DrawingCollectionSession


def test_clipboard_rejects_duplicate_sketch_uuid_aliases() -> None:
    from uuid import UUID

    from mycad.core.drawing_collection_clipboard import (
        DrawingCollectionClipboard,
        decode_collection_clipboard,
        encode_collection_clipboard,
    )
    from mycad.core.drawing_text import TextStyleTable

    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (0, 0), (1, 0)),))
    other = replace(sketch, sketch_id=uuid4().hex)
    valid = DrawingCollectionClipboard((sketch, other), (), (), (), TextStyleTable())
    assert (
        decode_collection_clipboard(encode_collection_clipboard(valid)).sketches == valid.sketches
    )
    alias = replace(sketch, sketch_id=str(UUID(sketch.sketch_id)))
    payload = DrawingCollectionClipboard((sketch, alias), (), (), (), TextStyleTable())
    with pytest.raises(ValueError, match="草图身份重复"):
        encode_collection_clipboard(payload)


def test_collection_clipboard_paste_copies_complete_group_atomically() -> None:
    from mycad.core.drawing_collection_clipboard import (
        capture_collection_clipboard,
        decode_collection_clipboard,
        encode_collection_clipboard,
        prepare_collection_paste,
    )
    from mycad.core.drawing_raster import DrawingRaster

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    text = DrawingText(uuid4().hex, "文字", (1, 1))
    session.stage(ReplayAppend("drawing.text.add", 1, text.to_mapping(), "local"))
    picture = DrawingRaster(
        uuid4().hex,
        "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAACXBIWXMAAA7EAAAOxAGVKw4b"
        "AAAAFElEQVQImWNk+M/wn4GBgYGJAQoAHhgCAh6YW2QAAAAASUVORK5CYII=",
        (3, 2),
        2,
        2,
    )
    session.stage(
        ReplayAppend(
            "drawing.raster.batch",
            2,
            {"action": "add", "images": [picture.to_mapping(version=2)]},
            "local",
        )
    )
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (ref, DrawingObjectRef("text", text.text_id), DrawingObjectRef("raster", picture.image_id)),
        name="G",
    )
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    payload = capture_collection_clipboard(session.snapshot, (ref,))
    encoded = encode_collection_clipboard(payload)
    decoded = decode_collection_clipboard(encoded)
    legacy = cast("dict[str, object]", json.loads(encoded))
    legacy["version"] = 1
    legacy.pop("layers")
    legacy.pop("dimension_styles")
    legacy.pop("frames")
    legacy.pop("datums")
    legacy.pop("reference_dimensions")
    legacy.pop("cross_tangencies")
    legacy.pop("block_definitions")
    legacy.pop("block_instances")
    assert decode_collection_clipboard(json.dumps(legacy).encode()).groups == payload.groups
    session.stage(prepare_collection_paste(decoded, session.snapshot, (0, 3)))
    assert len(session.snapshot.groups) == 2
    copied_group = session.snapshot.groups[1]
    assert copied_group.group_id != group.group_id and copied_group.name != group.name
    copied_geometry = next(item for item in copied_group.members if item.kind == "geometry")
    copied_text = next(item for item in copied_group.members if item.kind == "text")
    copied_picture = next(item for item in copied_group.members if item.kind == "raster")
    assert copied_geometry.object_id != line.entity_id and copied_text.object_id != text.text_id
    assert copied_picture.object_id != picture.image_id
    assert session.snapshot.texts[-1].position_mm == (1, 4)
    assert session.snapshot.rasters[-1].origin_mm == (3, 5)
    session.undo()
    assert session.snapshot.groups == (group,) and session.snapshot.texts == (text,)
    assert session.snapshot.rasters == (picture,)
    session.redo()
    assert session.snapshot.groups[-1] == copied_group
    session.stage(prepare_collection_paste(decoded, session.snapshot, (0, 6)))
    second_group = session.snapshot.groups[-1]
    assert second_group.group_id not in {group.group_id, copied_group.group_id}
    assert second_group.name not in {group.name, copied_group.name}
    assert not set(second_group.members).intersection(copied_group.members)
    session.cancel()


def test_text_only_group_paste_reconciles_styles_across_documents(tmp_path: Path) -> None:
    from mycad.core.drawing_collection_clipboard import (
        capture_collection_clipboard,
        decode_collection_clipboard,
        encode_collection_clipboard,
        prepare_collection_paste,
    )
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    source = app.new_workspace_document(services, kind="sketch")
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    session = DrawingCollectionSession(
        services,
        source,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    text = DrawingText(uuid4().hex, "文字", (1, 1))
    styles = TextStyleTable((TextStyle(height_mm=7),), "standard")
    session.stage(
        ReplayAppend(
            "drawing.text.batch",
            1,
            {"add": [text.to_mapping()], "styles": styles.to_mapping()},
            "local",
        )
    )
    ref = DrawingObjectRef("text", text.text_id)
    group = DrawingGroup(uuid4().hex, (ref,), name="说明")
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    data = encode_collection_clipboard(capture_collection_clipboard(session.snapshot, (ref,)))
    session.cancel()

    target = app.new_workspace_document(services, kind="sketch")
    empty = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    target_session = DrawingCollectionSession(
        services,
        target,
        ReplayAppend("sketch.create", 58, empty.to_state_mapping(), "local"),
        session_identity=2,
    )
    target_session.stage(
        prepare_collection_paste(decode_collection_clipboard(data), target_session.snapshot, (0, 3))
    )
    pasted = target_session.snapshot.texts[0]
    assert pasted.text_id != text.text_id and pasted.style_id != "standard"
    assert target_session.snapshot.text_styles.get(pasted.style_id).height_mm == 7
    assert target_session.snapshot.text_styles.get("standard").height_mm != 7
    target_session.commit()
    assert services.kernel.sketches == ()
    path = tmp_path / "text-group-paste.my2d"
    save_document(target.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_texts == () and services.kernel.drawing_groups == ()
    assert len(services.kernel.drawing_text_styles.styles) == 1


def test_clipboard_rejects_locked_member_and_dangling_group() -> None:
    from mycad.core.drawing_collection_clipboard import (
        capture_collection_clipboard,
        decode_collection_clipboard,
        encode_collection_clipboard,
    )
    from mycad.core.exceptions import ValidationError
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    snapshot = session.snapshot
    payload = capture_collection_clipboard(snapshot, (ref,))
    locked_layers = snapshot.layers.add(SketchLayer("Locked", locked=True))
    locked_line = replace(line, layer_name="Locked")
    locked = replace(
        snapshot,
        sketches=(replace(draft, entities=(locked_line,), layers=locked_layers),),
        layers=locked_layers,
    )
    with pytest.raises(ValidationError, match="锁定"):
        capture_collection_clipboard(locked, (ref,))
    encoded = cast("dict[str, object]", json.loads(encode_collection_clipboard(payload)))
    groups = cast("list[dict[str, object]]", encoded["groups"])
    members = cast("list[dict[str, object]]", groups[0]["members"])
    members[0]["object_id"] = uuid4().hex
    with pytest.raises(ValueError, match="成员"):
        decode_collection_clipboard(json.dumps(encoded).encode())
    assert session.snapshot == snapshot
    session.cancel()


def test_clipboard_allows_unrelated_array_but_rejects_its_source() -> None:
    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.drawing_collection_clipboard import capture_collection_clipboard
    from mycad.core.exceptions import ValidationError

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    lines = tuple(LineEntity(uuid4().hex, (0, y), (2, y)) for y in (0, 5, 10))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    source = ArrayEntityRef(draft.sketch_id, lines[0].entity_id)
    target = ArrayEntityRef(draft.sketch_id, lines[1].entity_id)
    array = AssociativeRectArray(
        uuid4().hex, draft.frame, 1, 2, 0, 5, (source,), (ArrayMember(source, target, 0, 1),)
    )
    snapshot = replace(session.snapshot, associative_arrays=(array,))
    unrelated = DrawingObjectRef("geometry", lines[2].entity_id, draft.sketch_id)
    assert capture_collection_clipboard(snapshot, (unrelated,)).sketches[0].entities == (lines[2],)
    with pytest.raises(ValidationError, match="阵列"):
        capture_collection_clipboard(
            snapshot, (DrawingObjectRef("geometry", lines[0].entity_id, draft.sketch_id),)
        )
    session.cancel()


def test_text_group_clipboard_imports_missing_layer_atomically(tmp_path: Path) -> None:
    from mycad.core.drawing_collection_clipboard import (
        capture_collection_clipboard,
        decode_collection_clipboard,
        encode_collection_clipboard,
        prepare_collection_paste,
    )
    from mycad.core.persistence import save_document
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable

    services = app.build_app(discoverers=[])
    source = app.new_workspace_document(services, kind="sketch")
    layers = SketchLayerTable().add(SketchLayer("Detail", color_rgb=(40, 80, 120)))
    source_line = LineEntity(uuid4().hex, (0, 0), (2, 0), layer_name="Detail")
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source_line,), layers=layers)
    app.commit_new_sketch(services, source, saved, session_identity=1)
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    session = DrawingCollectionSession(
        services,
        source,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    text = DrawingText(uuid4().hex, "文字", (1, 1), layer_name="Detail")
    session.stage(ReplayAppend("drawing.text.add", 1, text.to_mapping(), "local"))
    ref = DrawingObjectRef("text", text.text_id)
    group = DrawingGroup(uuid4().hex, (ref,))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    data = encode_collection_clipboard(capture_collection_clipboard(session.snapshot, (ref,)))
    session.cancel()
    target = app.new_workspace_document(services, kind="sketch")
    empty = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    target_session = DrawingCollectionSession(
        services,
        target,
        ReplayAppend("sketch.create", 58, empty.to_state_mapping(), "local"),
        session_identity=2,
    )
    target_session.stage(
        prepare_collection_paste(decode_collection_clipboard(data), target_session.snapshot, (0, 3))
    )
    assert target_session.snapshot.layers.get("Detail").color_rgb == (40, 80, 120)
    assert target_session.snapshot.texts[0].layer_name == "Detail"
    target_session.commit()
    path = tmp_path / "layer-group-paste.my2d"
    save_document(target.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_texts == () and services.kernel.drawing_groups == ()
    with pytest.raises(KeyError):
        services.kernel.drawing_layers.get("Detail")


def test_group_paste_layer_survives_subsequent_sketch_revision(tmp_path: Path) -> None:
    from mycad.core.drawing_collection_clipboard import (
        DrawingCollectionClipboard,
        prepare_collection_paste,
    )
    from mycad.core.drawing_text import TextStyleTable
    from mycad.core.persistence import save_document
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable

    services = app.build_app(discoverers=[])
    target = app.new_workspace_document(services, kind="sketch")
    empty = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    session = DrawingCollectionSession(
        services,
        target,
        ReplayAppend("sketch.create", 58, empty.to_state_mapping(), "local"),
        session_identity=1,
    )
    layers = SketchLayerTable().add(SketchLayer("Detail"))
    line = LineEntity(uuid4().hex, (0, 0), (2, 0), layer_name="Detail")
    source = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), layers=layers)
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", line.entity_id, source.sketch_id),)
    )
    payload = DrawingCollectionClipboard((source,), (), (), (group,), TextStyleTable(), layers)
    session.stage(prepare_collection_paste(payload, session.snapshot, (0, 3)))
    pasted = next(item for item in session.snapshot.sketches if item.sketch_id != empty.sketch_id)
    pasted_line = pasted.entities[0]
    assert isinstance(pasted_line, LineEntity)
    revised = replace(pasted, entities=(replace(pasted_line, start_mm=(0, 4), end_mm=(2, 4)),))
    state = revised.to_state_mapping()
    session.stage(
        ReplayAppend(
            "drawing.sketch.revise",
            79,
            {
                "revisions": [
                    {
                        "sketch_id": pasted.sketch_id,
                        "base_state_sha256": pasted.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
        )
    )
    session.commit()
    assert services.kernel.drawing_layers.get("Detail")
    assert len(services.kernel.drawing_groups) == 1
    path = tmp_path / "layer-paste-revision.my2d"
    save_document(target.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups and services.kernel.drawing_layers.get("Detail")
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == () and services.kernel.sketches == ()
    with pytest.raises(KeyError):
        services.kernel.drawing_layers.get("Detail")


def test_paste_failure_after_layer_step_rolls_back_everything() -> None:
    from mycad.core.drawing_collection_clipboard import (
        DrawingCollectionClipboard,
        prepare_collection_paste,
    )
    from mycad.core.drawing_text import TextStyleTable
    from mycad.core.exceptions import ValidationError
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable

    services = app.build_app(discoverers=[])
    target = app.new_workspace_document(services, kind="sketch")
    empty = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    session = DrawingCollectionSession(
        services,
        target,
        ReplayAppend("sketch.create", 58, empty.to_state_mapping(), "local"),
        session_identity=1,
    )
    layers = SketchLayerTable().add(SketchLayer("Detail"))
    text = DrawingText(uuid4().hex, "文字", (1, 1), layer_name="Detail")
    group = DrawingGroup(uuid4().hex, (DrawingObjectRef("text", text.text_id),))
    payload = DrawingCollectionClipboard((), (text,), (), (group,), TextStyleTable(), layers)
    operation = prepare_collection_paste(payload, session.snapshot, (0, 3))
    params = deepcopy(dict(operation.params))
    steps = cast("list[dict[str, object]]", params["operations"])
    assert steps[0]["id"] == "drawing.layers.set"
    text_params = cast("dict[str, object]", steps[1]["params"])
    text_additions = cast("list[dict[str, object]]", text_params["add"])
    text_additions[0]["style_id"] = "missing-style"
    before = session.snapshot
    checkpoint = session.checkpoint()
    with pytest.raises(ValidationError):
        session.stage(ReplayAppend("drawing.objects.batch", 1, params, "local"))
    assert session.snapshot == before and session.checkpoint() == checkpoint
    assert target.document.commands == () and services.kernel.drawing_texts == ()
    with pytest.raises(KeyError):
        session.snapshot.layers.get("Detail")
    session.cancel()


def test_group_clipboard_reports_missing_dimension_geometry() -> None:
    from mycad.core.drawing_collection_clipboard import capture_collection_clipboard
    from mycad.core.exceptions import ValidationError
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(line.entity_id, "geometry"),), 10, "mm"
    )
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    text = DrawingText(uuid4().hex, "说明", (1, 1))
    session.stage(ReplayAppend("drawing.text.add", 1, text.to_mapping(), "local"))
    dim_ref = DrawingObjectRef("dimension", dimension.constraint_id, draft.sketch_id)
    text_ref = DrawingObjectRef("text", text.text_id)
    group = DrawingGroup(uuid4().hex, (dim_ref, text_ref))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    before = session.snapshot
    checkpoint = session.checkpoint()
    with pytest.raises(ValidationError, match="尺寸.*全部关联几何"):
        capture_collection_clipboard(before, (text_ref,))
    assert session.snapshot == before and session.checkpoint() == checkpoint
    assert loaded.document.commands == ()
    session.cancel()


def test_group_clipboard_copies_dimension_and_rebinds_geometry(tmp_path: Path) -> None:
    from mycad.core.drawing_collection_clipboard import (
        capture_collection_clipboard,
        decode_collection_clipboard,
        encode_collection_clipboard,
        prepare_collection_paste,
    )
    from mycad.core.persistence import save_document
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    source = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        position_mm=(5, 2),
    )
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    session = DrawingCollectionSession(
        services,
        source,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex, (ref, DrawingObjectRef("dimension", dimension.constraint_id, draft.sketch_id))
    )
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    data = encode_collection_clipboard(capture_collection_clipboard(session.snapshot, (ref,)))
    session.cancel()
    target = app.new_workspace_document(services, kind="sketch")
    empty = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    target_session = DrawingCollectionSession(
        services,
        target,
        ReplayAppend("sketch.create", 58, empty.to_state_mapping(), "local"),
        session_identity=2,
    )
    target_session.stage(
        prepare_collection_paste(decode_collection_clipboard(data), target_session.snapshot, (0, 3))
    )
    copied = target_session.snapshot.groups[0]
    geometry = next(item for item in copied.members if item.kind == "geometry")
    copied_dimension = next(item for item in copied.members if item.kind == "dimension")
    copied_sketch = next(
        item for item in target_session.snapshot.sketches if item.sketch_id == geometry.sketch_id
    )
    assert copied_dimension.sketch_id == copied_sketch.sketch_id
    assert copied_sketch.constraints[0].constraint_id == copied_dimension.object_id
    assert copied_sketch.constraints[0].references[0].entity_id == geometry.object_id
    assert copied_sketch.constraints[0].position_mm == (5, 5)
    target_session.commit()
    path = tmp_path / "dimension-group-paste.my2d"
    save_document(target.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.sketches == () and services.kernel.drawing_groups == ()


def test_group_clipboard_reconciles_named_dimension_style_and_font(tmp_path: Path) -> None:
    from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
    from mycad.core.drawing_collection_clipboard import (
        capture_collection_clipboard,
        decode_collection_clipboard,
        encode_collection_clipboard,
        prepare_collection_paste,
    )
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.persistence import save_document
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    source = app.new_workspace_document(services, kind="sketch")
    source_fonts = TextStyleTable((TextStyle(height_mm=7),), "standard")
    source.bus.execute("drawing.text_styles.set", source_fonts.to_mapping(), "local", version=1)
    source_style = DimensionStyle("Shared", text_height=5, text_style_id="standard")
    source_styles = DimensionStyleTable((source_style,), "Shared")
    source.bus.execute(
        "drawing.dimension_styles.set", source_styles.to_mapping(), "local", version=10
    )
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        style_name="Shared",
    )
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    session = DrawingCollectionSession(
        services,
        source,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex, (ref, DrawingObjectRef("dimension", dimension.constraint_id, draft.sketch_id))
    )
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    data = encode_collection_clipboard(capture_collection_clipboard(session.snapshot, (ref,)))
    session.cancel()

    target = app.new_workspace_document(services, kind="sketch")
    existing = DimensionStyle("Shared", text_height=8)
    target_styles = DimensionStyleTable((existing,), "Shared")
    target.bus.execute(
        "drawing.dimension_styles.set", target_styles.to_mapping(), "local", version=10
    )
    empty = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    target_session = DrawingCollectionSession(
        services,
        target,
        ReplayAppend("sketch.create", 58, empty.to_state_mapping(), "local"),
        session_identity=2,
    )
    target_session.stage(
        prepare_collection_paste(decode_collection_clipboard(data), target_session.snapshot, (0, 3))
    )
    snapshot = target_session.snapshot
    copied = next(item for item in snapshot.sketches if item.sketch_id != empty.sketch_id)
    name = copied.constraints[0].style_name
    assert name is not None and name != "Shared"
    assert snapshot.dimension_styles.get("Shared") == existing
    imported = snapshot.dimension_styles.get(name)
    assert imported.text_height == 5 and imported.text_style_id is not None
    assert snapshot.text_styles.get(imported.text_style_id).height_mm == 7
    copied_line = copied.entities[0]
    assert isinstance(copied_line, LineEntity)
    revised = replace(copied, entities=(replace(copied_line, start_mm=(0, 4), end_mm=(10, 4)),))
    revised_state = revised.to_state_mapping()
    target_session.stage(
        ReplayAppend(
            "drawing.sketch.revise",
            79,
            {
                "revisions": [
                    {
                        "sketch_id": copied.sketch_id,
                        "base_state_sha256": copied.local_state_digest(),
                        "entities": revised_state["entities"],
                        "constraints": revised_state["constraints"],
                    }
                ]
            },
            "local",
        )
    )
    target_session.commit()
    path = tmp_path / "dimension-style-group.my2d"
    save_document(target.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_dimension_styles.get(name) == imported
    assert services.kernel.drawing_groups
    reopened.bus.undo_operation()
    assert services.kernel.drawing_dimension_styles == target_styles
    assert services.kernel.drawing_groups == ()
    assert len(services.kernel.drawing_text_styles.styles) == 1
    reopened.bus.redo_operation()
    assert services.kernel.drawing_dimension_styles.get(name) == imported
    reopened.bus.redo_operation()


def test_group_clipboard_rebinds_attached_annotations_across_documents(tmp_path: Path) -> None:
    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.drawing_collection_clipboard import (
        capture_collection_clipboard,
        decode_collection_clipboard,
        encode_collection_clipboard,
        prepare_collection_paste,
    )
    from mycad.core.drawing_raster import DrawingRaster
    from mycad.core.geometric_tolerance import (
        DatumAttachment,
        DatumIdentifier,
        DatumReference,
        FeatureControlFrame,
        ToleranceRow,
    )
    from mycad.core.persistence import save_document
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=[])
    source = app.new_workspace_document(services, kind="sketch")
    original_history = tuple(source.document.commands)
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        source,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (4, 4),
        (0, 0),
        attachment=DatumAttachment(
            draft.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2, datums=(DatumReference("A", datum.datum_id),)),),
        (5, 5),
    )
    reference = DetachedDimension(uuid4().hex, "aligned", (0, 2), (2, 2), (1, 3), 0, 2)
    image = DrawingRaster(
        uuid4().hex,
        "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAACXBIWXMAAA7EAAAOxAGVKw4b"
        "AAAAFElEQVQImWNk+M/wn4GBgYGJAQoAHhgCAh6YW2QAAAAASUVORK5CYII=",
        (8, 2),
        2,
        2,
    )
    definition = BlockDefinition(
        uuid4().hex, "AnnotationBlock", (LineEntity(uuid4().hex, (0, 0), (3, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (10, 3))
    session.stage(ReplayAppend("drawing.block.create", 1, definition.to_mapping(), "local"))
    session.stage(ReplayAppend("drawing.block_instance.insert", 1, instance.to_mapping(), "local"))
    session.stage(
        ReplayAppend(
            "drawing.raster.batch",
            2,
            {"action": "add", "images": [image.to_mapping(version=2)]},
            "local",
        )
    )
    session.stage(
        ReplayAppend(
            "drawing.tolerance.batch",
            28,
            {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
            "local",
        )
    )
    session.stage(
        ReplayAppend(
            "drawing.reference_dimensions.batch", 10, {"add": [reference.to_mapping()]}, "local"
        )
    )
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (
            ref,
            DrawingObjectRef("tolerance", frame.frame_id),
            DrawingObjectRef("datum", datum.datum_id),
            DrawingObjectRef("reference_dimension", reference.dimension_id),
            DrawingObjectRef("raster", image.image_id),
            DrawingObjectRef("block_instance", instance.instance_id),
        ),
    )
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    data = encode_collection_clipboard(
        capture_collection_clipboard(
            session.snapshot, (DrawingObjectRef("block_instance", instance.instance_id),)
        )
    )
    session.cancel()
    assert tuple(source.document.commands) == original_history
    assert not services.kernel.drawing_groups and not services.kernel.drawing_block_instances

    target = app.new_workspace_document(services, kind="sketch")
    empty = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    target_session = DrawingCollectionSession(
        services,
        target,
        ReplayAppend("sketch.create", 58, empty.to_state_mapping(), "local"),
        session_identity=2,
    )
    target_session.stage(
        prepare_collection_paste(decode_collection_clipboard(data), target_session.snapshot, (0, 3))
    )
    snapshot = target_session.snapshot
    copied_group = snapshot.groups[0]
    copied_geom = next(item for item in copied_group.members if item.kind == "geometry")
    copied_datum = snapshot.datums[0]
    assert copied_datum.attachment is not None
    assert copied_datum.attachment.sketch_id == copied_geom.sketch_id
    assert copied_datum.attachment.reference.entity_id == copied_geom.object_id
    assert copied_datum.position_mm == (4, 7) and copied_datum.target_mm == (0, 3)
    assert snapshot.frames[0].rows[0].datums[0].datum_id == copied_datum.datum_id
    assert snapshot.reference_dimensions[0].location_mm == (1, 6)
    assert snapshot.rasters[0].origin_mm == (8, 5)
    assert snapshot.rasters[0].png_base64 == image.png_base64
    assert snapshot.block_instances[0].insertion_mm == (10, 6)
    assert snapshot.block_instances[0].definition_id == snapshot.block_definitions[0].definition_id
    assert len(copied_group.members) == 6
    target_session.commit()
    path = tmp_path / "annotation-group-paste.my2d"
    save_document(target.document, path)
    reopened = app.open_app_document(services, path)
    restored = app.drawing_collection_snapshot(services)
    assert (
        restored.rasters == snapshot.rasters
        and restored.block_instances == snapshot.block_instances
    )
    assert restored.datums[0].attachment == copied_datum.attachment
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == () and services.kernel.drawing_datum_identifiers == ()
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == restored
    from mycad.formats.dxf_preview import prepare_dxf_output_preview
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    preview = prepare_dxf_output_preview(services.kernel)
    assert any("图片未导出" in warning for warning in preview.report.warnings)
    assert any("组" in warning and "不完整" in warning for warning in preview.report.warnings)
    exchange = tmp_path / "annotation-group-paste.dxf"
    exchange.write_bytes(preview.dxf_bytes)
    imported = read_sketch_dxf(exchange)
    assert len(imported.groups) == 1 and len(imported.groups[0].members) == 5
    assert imported.datum_identifiers[0].attachment is not None
    assert (
        imported.datum_identifiers[0].attachment.reference.entity_id
        == imported.sketch.entities[0].entity_id
    )
    assert (
        imported.tolerance_frames[0].rows[0].datums[0].datum_id
        == imported.datum_identifiers[0].datum_id
    )


def test_collection_clipboard_preserves_complete_cross_sketch_tangency(tmp_path: Path) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.drawing_collection_clipboard import (
        capture_collection_clipboard,
        decode_collection_clipboard,
        encode_collection_clipboard,
        prepare_collection_paste,
    )
    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    refs = (
        DrawingObjectRef("geometry", line.entity_id, first.sketch_id),
        DrawingObjectRef("geometry", circle.entity_id, second.sketch_id),
    )
    group = DrawingGroup(uuid4().hex, refs)
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    payload = decode_collection_clipboard(
        encode_collection_clipboard(capture_collection_clipboard(session.snapshot, (refs[0],)))
    )
    assert payload.cross_tangencies == (relation,)
    malformed = cast("dict[str, object]", json.loads(encode_collection_clipboard(payload)))
    relations = cast("list[dict[str, object]]", malformed["cross_tangencies"])
    first_ref = cast("dict[str, object]", relations[0]["first"])
    first_ref["entity_id"] = uuid4().hex
    with pytest.raises(ValueError, match="相切关系引用"):
        decode_collection_clipboard(json.dumps(malformed).encode())
    session.stage(prepare_collection_paste(payload, session.snapshot, (0, 4)))
    assert len(session.snapshot.cross_tangencies) == 2
    copied = next(item for item in session.snapshot.cross_tangencies if item != relation)
    assert {
        (copied.first.sketch_id, copied.first.entity_id),
        (copied.second.sketch_id, copied.second.entity_id),
    } == {(item.sketch_id, item.object_id) for item in session.snapshot.groups[-1].members}
    session.undo()
    assert session.snapshot.cross_tangencies == (relation,)
    session.redo()
    assert set(session.snapshot.cross_tangencies) == {relation, copied}
    session.commit()
    path = tmp_path / "clipboard-tangency.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert set(services.kernel.cross_sketch_tangencies) == {relation, copied}
    reopened.bus.undo_operation()
    assert services.kernel.cross_sketch_tangencies == (relation,)
    target = app.new_workspace_document(services, kind="sketch")
    target_draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    target_session = DrawingCollectionSession(
        services,
        target,
        ReplayAppend("sketch.create", 3, target_draft.to_mapping(version=3), "local"),
        session_identity=2,
    )
    target_session.stage(prepare_collection_paste(payload, target_session.snapshot, (0, 0)))
    first_copy = target_session.snapshot.cross_tangencies[0]
    target_session.stage(prepare_collection_paste(payload, target_session.snapshot, (0, 4)))
    copies = target_session.snapshot.cross_tangencies
    assert len(copies) == 2 and first_copy in copies
    second_copy = next(item for item in copies if item != first_copy)
    assert first_copy.relation_id != second_copy.relation_id
    assert first_copy.first.sketch_id != second_copy.first.sketch_id
    target_session.cancel()


def test_boxed_datum_clipboard_relayout_is_validated_and_atomic(tmp_path: Path) -> None:
    from mycad.core.drawing_collection_clipboard import (
        capture_collection_clipboard,
        prepare_collection_paste,
    )
    from mycad.core.exceptions import ValidationError
    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    datum = DatumIdentifier(
        uuid4().hex, "A", (4, 4), (0, 0), layout_mode="shared", box_size_mm=(3, 3)
    )
    session.stage(
        ReplayAppend("drawing.tolerance.batch", 28, {"add_datums": [datum.to_mapping()]}, "local")
    )
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref, DrawingObjectRef("datum", datum.datum_id)))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    snapshot, checkpoint = session.snapshot, session.checkpoint()
    payload = capture_collection_clipboard(snapshot, (ref,))
    with pytest.raises(ValidationError, match="文字布局"):
        prepare_collection_paste(payload, snapshot, (0, 3))
    with pytest.raises(ValidationError, match="不能修改对象身份或关联"):
        prepare_collection_paste(
            payload,
            snapshot,
            (0, 3),
            datum_relayout=lambda item, styles: replace(item, datum_id=uuid4().hex),
        )
    assert session.snapshot == snapshot and session.checkpoint() == checkpoint
    operation = prepare_collection_paste(
        payload,
        snapshot,
        (0, 3),
        datum_relayout=lambda item, styles: replace(item, box_size_mm=(5, 4)),
    )
    session.stage(operation)
    copied = next(item for item in session.snapshot.datums if item.datum_id != datum.datum_id)
    assert copied.label == "B" and copied.box_size_mm == (5, 4)
    session.undo()
    assert session.snapshot == snapshot
    session.redo()
    session.commit()
    path = tmp_path / "boxed-datum-clipboard.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert set(services.kernel.drawing_datum_identifiers) == {datum, copied}
    reopened.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_clipboard_complete_group_with_external_tangency_copies_without_relation(
    tmp_path: Path,
) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.drawing_collection_clipboard import (
        capture_collection_clipboard,
        prepare_collection_paste,
    )
    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    ref = DrawingObjectRef("geometry", line.entity_id, first.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    payload = capture_collection_clipboard(session.snapshot, (ref,))
    assert payload.groups == (group,) and payload.cross_tangencies == ()
    session.stage(prepare_collection_paste(payload, session.snapshot, (0, 4)))
    assert len(session.snapshot.groups) == 2 and session.snapshot.cross_tangencies == (relation,)
    assert session.snapshot.groups[-1].members[0].object_id != line.entity_id
    session.undo()
    assert session.snapshot.groups == (group,) and session.snapshot.cross_tangencies == (relation,)
    session.redo()
    session.commit()
    path = tmp_path / "partial-tangency-clipboard.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert len(services.kernel.drawing_groups) == 2
    assert services.kernel.cross_sketch_tangencies == (relation,)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == (group,)
    assert services.kernel.cross_sketch_tangencies == (relation,)


def test_clipboard_complete_group_omits_external_local_constraint(tmp_path: Path) -> None:
    from mycad.core.drawing_collection_clipboard import (
        capture_collection_clipboard,
        prepare_collection_paste,
    )
    from mycad.core.persistence import save_document
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    second = LineEntity(uuid4().hex, (2, 0), (2, 3))
    relation = SketchConstraint(
        uuid4().hex,
        "coincident",
        (
            SketchGeometryReference(first.entity_id, "end"),
            SketchGeometryReference(second.entity_id, "start"),
        ),
    )
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second), (relation,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    ref = DrawingObjectRef("geometry", first.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    payload = capture_collection_clipboard(session.snapshot, (ref,))
    assert payload.groups == (group,) and payload.sketches[0].constraints == ()
    session.stage(prepare_collection_paste(payload, session.snapshot, (0, 4)))
    assert len(session.snapshot.groups) == 2
    original = next(item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id)
    assert original.constraints == (relation,) and original.entities == draft.entities
    copied = next(item for item in session.snapshot.sketches if item.sketch_id != draft.sketch_id)
    assert copied.constraints == () and len(copied.entities) == 1
    session.undo()
    assert session.snapshot.groups == (group,) and session.snapshot.sketches[-1] == draft
    session.redo()
    session.commit()
    path = tmp_path / "partial-local-clipboard.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert len(services.kernel.drawing_groups) == 2
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == (group,)
    assert services.kernel.sketches[0].constraints == (relation,)


def test_clipboard_ignores_unselected_locked_dimension_but_rejects_selected_one() -> None:
    from mycad.core.drawing_collection_clipboard import capture_collection_clipboard
    from mycad.core.exceptions import ValidationError
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        layer_name="Locked",
    )
    layers = services.kernel.drawing_layers.add(SketchLayer("Locked", locked=True))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,), layers)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    dim_ref = DrawingObjectRef("dimension", dimension.constraint_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,))
    snapshot = replace(session.snapshot, groups=(group,), layers=layers)
    assert capture_collection_clipboard(snapshot, (ref,)).sketches[0].constraints == ()
    selected = replace(snapshot, groups=(replace(group, members=(ref, dim_ref)),))
    with pytest.raises(ValidationError, match="锁定|隐藏"):
        capture_collection_clipboard(selected, (ref,))
    session.cancel()


def test_clipboard_roundtrips_block_only_and_group_with_definition() -> None:
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.drawing_collection_clipboard import (
        capture_collection_clipboard,
        decode_collection_clipboard,
        encode_collection_clipboard,
    )
    from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
    from mycad.core.drawing_text import DrawingText

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    definition = BlockDefinition(
        uuid4().hex,
        "Symbol",
        (LineEntity(uuid4().hex, (0, 0), (2, 0)),),
        (DrawingText(uuid4().hex, "Label", (1, 1)),),
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 3))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    ref = DrawingObjectRef("block_instance", instance.instance_id)
    group = DrawingGroup(uuid4().hex, (ref,))
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    payload = capture_collection_clipboard(app.drawing_collection_snapshot(services), (ref,))
    assert payload.sketches == () and payload.block_definitions == (definition,)
    assert payload.block_instances == (instance,) and payload.groups == (group,)
    assert decode_collection_clipboard(encode_collection_clipboard(payload)) == payload


def test_block_clipboard_paste_reuses_definition_and_remaps_conflicts(tmp_path: Path) -> None:
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.drawing_collection_clipboard import (
        capture_collection_clipboard,
        prepare_collection_paste,
    )
    from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
    from mycad.core.persistence import save_document

    source_services = app.build_app(discoverers=[])
    source = app.new_workspace_document(source_services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Symbol", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 3))
    group = DrawingGroup(uuid4().hex, (DrawingObjectRef("block_instance", instance.instance_id),))
    source.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    source.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    source.bus.execute("drawing.group.create", group.to_mapping(), "local")
    payload = capture_collection_clipboard(
        app.drawing_collection_snapshot(source_services), group.members
    )
    before = app.drawing_collection_snapshot(source_services)
    operation = prepare_collection_paste(payload, before, (10, 0))
    source.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    after = app.drawing_collection_snapshot(source_services)
    assert after.block_definitions == (definition,) and len(after.block_instances) == 2
    new_instance = after.block_instances[-1]
    assert (
        new_instance.instance_id != instance.instance_id
        and new_instance.definition_id == definition.definition_id
    )
    assert new_instance.insertion_mm == (15, 3)
    assert after.groups[-1].members == (
        DrawingObjectRef("block_instance", new_instance.instance_id),
    )
    path = tmp_path / "clipboard-block.my2d"
    save_document(source.document, path)
    reopened = app.open_app_document(source_services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(source_services) == before

    target_services = app.build_app(discoverers=[])
    target = app.new_workspace_document(target_services, kind="sketch")
    conflict = BlockDefinition(uuid4().hex, "Symbol", (replace(line, end_mm=(9, 0)),), ())
    target.bus.execute("drawing.block.create", conflict.to_mapping(), "local")
    operation = prepare_collection_paste(
        payload, app.drawing_collection_snapshot(target_services), (0, 2)
    )
    target.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    result = app.drawing_collection_snapshot(target_services)
    assert result.block_definitions[0] == conflict and len(result.block_definitions) == 2
    copied = result.block_definitions[-1]
    assert copied.definition_id != definition.definition_id and copied.name != definition.name
    assert len(copied.entities) == 1 and isinstance(copied.entities[0], LineEntity)
    assert copied.entities[0] == replace(line, entity_id=copied.entities[0].entity_id)
    assert copied.entities[0].entity_id != line.entity_id
    assert result.block_instances[-1].definition_id == copied.definition_id
    assert result.block_instances[-1].insertion_mm == (5, 5)


@pytest.mark.parametrize("same_content", [False, True])
@pytest.mark.parametrize("source_hyphen", [False, True])
def test_cross_document_block_paste_matches_uuid_alias_and_content(
    tmp_path: Path, same_content: bool, source_hyphen: bool
) -> None:
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.drawing_collection_clipboard import (
        capture_collection_clipboard,
        prepare_collection_paste,
    )
    from mycad.core.persistence import save_document

    source_services = app.build_app(discoverers=[])
    source = app.new_workspace_document(source_services, kind="sketch")
    identity = uuid4()
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    source_id = str(identity) if source_hyphen else identity.hex
    target_id = identity.hex if source_hyphen else str(identity)
    definition = BlockDefinition(source_id, "Shared", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 3))
    source.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    source.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    group = DrawingGroup(uuid4().hex, (DrawingObjectRef("block_instance", instance.instance_id),))
    source.bus.execute("drawing.group.create", group.to_mapping(), "local")
    payload = capture_collection_clipboard(
        app.drawing_collection_snapshot(source_services),
        (DrawingObjectRef("block_instance", instance.instance_id),),
    )
    target_services = app.build_app(discoverers=[])
    target = app.new_workspace_document(target_services, kind="sketch")
    target_line = line if same_content else replace(line, end_mm=(9, 0))
    existing = BlockDefinition(target_id, "Shared", (target_line,), ())
    target.bus.execute("drawing.block.create", existing.to_mapping(), "local")
    before = app.drawing_collection_snapshot(target_services)
    operation = prepare_collection_paste(payload, before, (0, 2))
    target.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    result = app.drawing_collection_snapshot(target_services)
    assert result.block_definitions[0] == existing
    assert result.groups[0].members == (
        DrawingObjectRef("block_instance", result.block_instances[0].instance_id),
    )
    if same_content:
        assert result.block_definitions == (existing,)
        assert result.block_instances[0].definition_id == existing.definition_id
    else:
        assert len(result.block_definitions) == 2
        copied = result.block_definitions[-1]
        assert copied.definition_id not in {identity.hex, str(identity)}
        assert copied.name == "Shared 副本"
        assert result.block_instances[0].definition_id == copied.definition_id
    path = tmp_path / "block-uuid-alias.my2d"
    save_document(target.document, path)
    reopened = app.open_app_document(target_services, path)
    assert app.drawing_collection_snapshot(target_services) == result
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(target_services) == before


def test_cross_document_block_copy_allocates_legacy_curve_point_ids(tmp_path: Path) -> None:
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.drawing_collection_clipboard import (
        capture_collection_clipboard,
        prepare_collection_paste,
    )
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, SplineEntity

    services = app.build_app(discoverers=[])
    source = app.new_workspace_document(services, kind="sketch")
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (2, 0), (2, 2)))
    spline = SplineEntity(uuid4().hex, ((0, 0), (1, 0), (2, 1), (3, 1)))
    definition = BlockDefinition(uuid4().hex, "Legacy", (polyline, spline), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0))
    source.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    source.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    payload = capture_collection_clipboard(
        app.drawing_collection_snapshot(services),
        (DrawingObjectRef("block_instance", instance.instance_id),),
    )
    target = app.new_workspace_document(services, kind="sketch")
    operation = prepare_collection_paste(payload, app.drawing_collection_snapshot(services), (1, 0))
    target.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    members = services.kernel.drawing_block_definitions[0].entities
    assert isinstance(members[0], PolylineEntity) and len(members[0].point_ids) == 3
    assert isinstance(members[1], SplineEntity) and len(members[1].point_ids) == 4
    assert set(members[0].point_ids).isdisjoint(members[1].point_ids)
    assert members[0].entity_id != polyline.entity_id and members[1].entity_id != spline.entity_id
    path = tmp_path / "legacy-block-paste.my2d"
    save_document(target.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_block_definitions[0].entities == members
    reopened.bus.undo_operation()
    assert services.kernel.drawing_block_definitions == ()
    reopened.bus.redo_operation()
    assert services.kernel.drawing_block_definitions[0].entities == members


def test_collection_paste_allocates_point_ids_for_legacy_curve(tmp_path: Path) -> None:
    from mycad.core.drawing_collection_clipboard import (
        capture_collection_clipboard,
        prepare_collection_paste,
    )
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity

    services = app.build_app(discoverers=[])
    source = app.new_workspace_document(services, kind="sketch")
    curve = PolylineEntity(uuid4().hex, ((0, 0), (2, 0), (2, 2)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    app.commit_new_sketch(services, source, sketch, session_identity=1)
    ref = DrawingObjectRef("geometry", curve.entity_id, sketch.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,))
    source.bus.execute("drawing.group.create", group.to_mapping(), "local")
    payload = capture_collection_clipboard(app.drawing_collection_snapshot(services), (ref,))
    target = app.new_workspace_document(services, kind="sketch")
    operation = prepare_collection_paste(payload, app.drawing_collection_snapshot(services), (5, 0))
    target.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    copied = services.kernel.sketches[-1].entities[0]
    assert isinstance(copied, PolylineEntity) and len(copied.point_ids) == 3
    assert copied.entity_id != curve.entity_id
    path = tmp_path / "legacy-group-paste.my2d"
    save_document(target.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches[-1].entities == (copied,)
    reopened.bus.undo_operation()
    assert services.kernel.sketches == ()
    reopened.bus.redo_operation()
    assert services.kernel.sketches[-1].entities == (copied,)


def test_block_clipboard_preserves_conflicting_text_style_across_documents() -> None:
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.drawing_collection_clipboard import (
        capture_collection_clipboard,
        prepare_collection_paste,
    )
    from mycad.core.drawing_text import TextStyle, TextStyleTable

    services = app.build_app(discoverers=[])
    source = app.new_workspace_document(services, kind="sketch")
    source_styles = TextStyleTable((TextStyle(height_mm=7),), "standard")
    source.bus.execute("drawing.text_styles.set", source_styles.to_mapping(), "local")
    text = DrawingText(uuid4().hex, "Styled", (1, 1))
    definition = BlockDefinition(uuid4().hex, "TextBlock", (), (text,))
    instance = BlockInstance(uuid4().hex, definition.definition_id, (2, 2))
    source.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    source.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    payload = capture_collection_clipboard(
        app.drawing_collection_snapshot(services),
        (DrawingObjectRef("block_instance", instance.instance_id),),
    )
    target = app.new_workspace_document(services, kind="sketch")
    before = app.drawing_collection_snapshot(services)
    assert before.text_styles.get("standard").height_mm != 7
    operation = prepare_collection_paste(payload, before, (1, 0))
    target.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    after = app.drawing_collection_snapshot(services)
    copied_text = after.block_definitions[0].texts[0]
    assert copied_text.text_id != text.text_id
    assert after.text_styles.get(copied_text.style_id).height_mm == 7
    assert after.text_styles.get("standard") == before.text_styles.get("standard")
    target.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before


@pytest.mark.parametrize("same_style", [False, True])
def test_same_identity_block_reuse_requires_matching_text_style_content(
    tmp_path: Path, same_style: bool
) -> None:
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.drawing_collection_clipboard import (
        capture_collection_clipboard,
        prepare_collection_paste,
    )
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    source = app.new_workspace_document(services, kind="sketch")
    source_style = TextStyle(height_mm=7, font_family="DejaVu Sans")
    source.bus.execute(
        "drawing.text_styles.set", TextStyleTable((source_style,), "standard").to_mapping(), "local"
    )
    text = DrawingText(uuid4().hex, "Styled", (1, 1))
    definition = BlockDefinition(uuid4().hex, "Shared", (), (text,))
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 5))
    group = DrawingGroup(uuid4().hex, (DrawingObjectRef("block_instance", instance.instance_id),))
    source.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    source.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    source.bus.execute("drawing.group.create", group.to_mapping(), "local")
    payload = capture_collection_clipboard(app.drawing_collection_snapshot(services), group.members)

    target = app.new_workspace_document(services, kind="sketch")
    target_style = source_style if same_style else replace(source_style, height_mm=4)
    target.bus.execute(
        "drawing.text_styles.set", TextStyleTable((target_style,), "standard").to_mapping(), "local"
    )
    target.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    before = app.drawing_collection_snapshot(services)
    operation = prepare_collection_paste(payload, before, (3, 0))
    target.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    result = app.drawing_collection_snapshot(services)
    assert len(result.block_definitions) == (1 if same_style else 2)
    copied = next(
        item
        for item in result.block_definitions
        if item.definition_id == result.block_instances[0].definition_id
    )
    assert (copied.definition_id == definition.definition_id) is same_style
    assert copied.name == ("Shared" if same_style else "Shared 副本")
    assert (copied.texts[0].text_id == text.text_id) is same_style
    assert result.text_styles.get(copied.texts[0].style_id).height_mm == 7
    assert result.text_styles.get("standard") == target_style
    assert result.groups[0].members == (
        DrawingObjectRef("block_instance", result.block_instances[0].instance_id),
    )
    path = tmp_path / f"style-conflict-{same_style}.my2d"
    save_document(target.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == result


def test_cross_document_group_preserves_shared_block_definition_and_text_style(
    tmp_path: Path,
) -> None:
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance, expand_block
    from mycad.core.drawing_collection_clipboard import (
        capture_collection_clipboard,
        prepare_collection_paste,
    )
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    source = app.new_workspace_document(services, kind="sketch")
    source_style = TextStyle(height_mm=7, font_family="DejaVu Sans")
    source.bus.execute(
        "drawing.text_styles.set", TextStyleTable((source_style,), "standard").to_mapping(), "local"
    )
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    text = DrawingText(uuid4().hex, "Shared", (1, 1))
    definition = BlockDefinition(uuid4().hex, "Shared", (line,), (text,))
    first = BlockInstance(uuid4().hex, definition.definition_id, (0, 0))
    second = BlockInstance(uuid4().hex, definition.definition_id, (10, 0), 90, 2)
    source.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    for instance in (first, second):
        source.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    group = DrawingGroup(
        uuid4().hex,
        tuple(DrawingObjectRef("block_instance", item.instance_id) for item in (first, second)),
        name="SharedInstances",
    )
    source.bus.execute("drawing.group.create", group.to_mapping(), "local")
    payload = capture_collection_clipboard(app.drawing_collection_snapshot(services), group.members)
    target = app.new_workspace_document(services, kind="sketch")
    conflict = BlockDefinition(
        uuid4().hex, "Shared", (LineEntity(uuid4().hex, (0, 0), (9, 0)),), ()
    )
    target.bus.execute("drawing.block.create", conflict.to_mapping(), "local")
    before = app.drawing_collection_snapshot(services)
    operation = prepare_collection_paste(payload, before, (3, 4))
    target.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    result = app.drawing_collection_snapshot(services)
    assert result.block_definitions[0] == conflict and len(result.block_definitions) == 2
    copied = result.block_definitions[1]
    assert copied.name == "Shared 副本" and copied.definition_id != definition.definition_id
    assert len(result.block_instances) == 2
    assert all(item.definition_id == copied.definition_id for item in result.block_instances)
    assert len({item.instance_id for item in result.block_instances}) == 2
    assert result.groups[0].members == tuple(
        DrawingObjectRef("block_instance", item.instance_id) for item in result.block_instances
    )
    assert result.text_styles.get(copied.texts[0].style_id).height_mm == 7
    assert result.text_styles.get("standard") == before.text_styles.get("standard")
    expansions = tuple(
        expand_block(copied, item, result.text_styles) for item in result.block_instances
    )
    assert expansions[0].texts[0].position_mm == pytest.approx((4, 5))
    assert expansions[1].texts[0].position_mm == pytest.approx((11, 6))
    assert expansions[0].texts[0].height_mm == pytest.approx(7)
    assert expansions[1].texts[0].height_mm == pytest.approx(14)
    updated = replace(copied, texts=(replace(copied.texts[0], text="Edited"),))
    target.bus.execute("drawing.block.update", updated.to_mapping(), "local")
    edited = app.drawing_collection_snapshot(services)
    assert all(
        expand_block(updated, item, edited.text_styles).texts[0].text == "Edited"
        for item in edited.block_instances
    )
    path = tmp_path / "shared-cross-document.my2d"
    save_document(target.document, path)
    reopened = app.open_app_document(services, path)
    assert app.drawing_collection_snapshot(services) == edited
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == result
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == result
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == edited


def test_block_clipboard_rejects_corruption_and_locked_effective_layer() -> None:
    from uuid import UUID

    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.drawing_collection_clipboard import (
        capture_collection_clipboard,
        decode_collection_clipboard,
        encode_collection_clipboard,
        prepare_collection_paste,
    )
    from mycad.core.exceptions import ValidationError
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    layers = services.kernel.drawing_layers.add(SketchLayer("Insert"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    definition = BlockDefinition(
        uuid4().hex, "Block", (LineEntity(uuid4().hex, (0, 0), (2, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0), layer_name="Insert")
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    ref = DrawingObjectRef("block_instance", instance.instance_id)
    snapshot = app.drawing_collection_snapshot(services)
    payload = capture_collection_clipboard(snapshot, (ref,))
    raw = cast("dict[str, object]", json.loads(encode_collection_clipboard(payload)))
    raw["block_definitions"] = []
    with pytest.raises(ValueError, match="定义"):
        decode_collection_clipboard(json.dumps(raw).encode())
    raw = cast("dict[str, object]", json.loads(encode_collection_clipboard(payload)))
    raw["block_instances"] = [instance.to_mapping(), instance.to_mapping()]
    with pytest.raises(ValueError, match="重复"):
        decode_collection_clipboard(json.dumps(raw).encode())
    raw = cast("dict[str, object]", json.loads(encode_collection_clipboard(payload)))
    raw["block_instances"] = [
        instance.to_mapping(),
        replace(instance, instance_id=str(UUID(instance.instance_id))).to_mapping(),
    ]
    with pytest.raises(ValueError, match="块实例身份重复"):
        decode_collection_clipboard(json.dumps(raw).encode())
    raw = cast("dict[str, object]", json.loads(encode_collection_clipboard(payload)))
    raw["block_definitions"] = [
        definition.to_mapping(),
        replace(
            definition, definition_id=str(UUID(definition.definition_id)), name="Other"
        ).to_mapping(),
    ]
    with pytest.raises(ValueError, match="块定义身份重复"):
        decode_collection_clipboard(json.dumps(raw).encode())
    locked = layers.replace(replace(layers.get("Insert"), locked=True))
    blocked = replace(snapshot, layers=locked)
    history = tuple(loaded.document.commands)
    with pytest.raises(ValidationError, match="锁定"):
        capture_collection_clipboard(blocked, (ref,))
    with pytest.raises(ValidationError, match="锁定"):
        prepare_collection_paste(payload, blocked, (1, 0))
    assert (
        tuple(loaded.document.commands) == history
        and app.drawing_collection_snapshot(services) == snapshot
    )


def test_cross_document_block_paste_uses_instance_layer_when_zero_locked(tmp_path: Path) -> None:
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.drawing_collection_clipboard import (
        capture_collection_clipboard,
        prepare_collection_paste,
    )
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=[])
    source = app.new_workspace_document(services, kind="sketch")
    layers = services.kernel.drawing_layers.add(SketchLayer("Insert"))
    source.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    definition = BlockDefinition(
        uuid4().hex, "Inherited", (LineEntity(uuid4().hex, (0, 0), (2, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 3), layer_name="Insert")
    source.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    source.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    payload = capture_collection_clipboard(
        app.drawing_collection_snapshot(services),
        (DrawingObjectRef("block_instance", instance.instance_id),),
    )
    target = app.new_workspace_document(services, kind="sketch")
    target_layers = services.kernel.drawing_layers.add(SketchLayer("Insert"))
    target_layers = target_layers.replace(replace(target_layers.get("0"), locked=True))
    target.bus.execute(
        "drawing.layers.set",
        {"layers": target_layers.to_mapping(), "dimension_layer": "DIM"},
        "local",
    )
    before = app.drawing_collection_snapshot(services)
    operation = prepare_collection_paste(payload, before, (0, 2))
    target.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    result = app.drawing_collection_snapshot(services)
    assert len(result.block_instances) == 1 and result.block_instances[0].layer_name == "Insert"
    assert result.block_definitions[0].entities[0].layer_name == "0"
    assert result.layers.get("0").locked
    from mycad.core.persistence import save_document

    path = tmp_path / "inherited-layer.my2d"
    save_document(target.document, path)
    reopened = app.open_app_document(services, path)
    assert app.drawing_collection_snapshot(services) == result
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before


def test_group_clipboard_handles_unselected_external_datum_by_source_identity() -> None:
    from mycad.core.drawing_collection_clipboard import (
        capture_collection_clipboard,
        decode_collection_clipboard,
        encode_collection_clipboard,
        prepare_collection_paste,
    )
    from mycad.core.exceptions import ValidationError
    from mycad.core.geometric_tolerance import (
        DatumIdentifier,
        DatumReference,
        FeatureControlFrame,
        ToleranceRow,
    )

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, sketch.to_mapping(version=3), "local"),
        session_identity=1,
    )
    datum = DatumIdentifier(uuid4().hex, "A", (0, 5), (0, 0))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2, datums=(DatumReference("A", datum.datum_id),)),),
        (10, 5),
    )
    session.stage(
        ReplayAppend(
            "drawing.tolerance.batch",
            28,
            {
                "add_datums": [datum.to_mapping()],
                "add_frames": [frame.to_mapping()],
            },
            "local",
        )
    )
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),
            DrawingObjectRef("tolerance", frame.frame_id),
        ),
    )
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    payload = capture_collection_clipboard(
        session.snapshot, group.members, source_token=uuid4().hex
    )
    encoded = encode_collection_clipboard(payload)
    raw = cast("dict[str, object]", json.loads(encoded))
    assert raw["version"] == 8
    malformed_cases: tuple[tuple[str, object], ...] = (
        ("source_token", "invalid"),
        ("external_objects", []),
    )
    for field, value in malformed_cases:
        malformed = deepcopy(raw)
        malformed[field] = value
        with pytest.raises(ValueError):
            decode_collection_clipboard(json.dumps(malformed).encode())
    payload = decode_collection_clipboard(encoded)
    same = session.preview_operation(
        prepare_collection_paste(
            payload,
            session.snapshot,
            (5, 0),
            preserve_external=True,
        )
    )
    assert same.frames[-1].rows[0].datums[0].datum_id == datum.datum_id
    assert len(same.datums) == 1 and len(same.groups) == 2
    other = session.preview_operation(
        prepare_collection_paste(
            payload,
            session.snapshot,
            (5, 0),
            preserve_external=False,
        )
    )
    assert other.frames[-1].rows[0].datums[0].datum_id is None
    assert other.frames[-1].rows[0].datums[0].label == "A"
    stale = replace(session.snapshot, datums=(replace(datum, label="B"),))
    with pytest.raises(ValidationError, match="关联|变化"):
        prepare_collection_paste(payload, stale, (5, 0), preserve_external=True)


def test_group_clipboard_external_geometry_rebinds_only_in_source_document() -> None:
    from mycad.core.drawing_collection_clipboard import (
        capture_collection_clipboard,
        decode_collection_clipboard,
        encode_collection_clipboard,
        prepare_collection_paste,
    )
    from mycad.core.exceptions import ValidationError
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    external = LineEntity(uuid4().hex, (0, 0), (10, 0))
    selected = LineEntity(uuid4().hex, (0, 10), (10, 10))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (external, selected))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, sketch.to_mapping(version=3), "local"),
        session_identity=1,
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (2, 2),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(external.entity_id, "start")
        ),
    )
    session.stage(
        ReplayAppend("drawing.tolerance.batch", 28, {"add_datums": [datum.to_mapping()]}, "local")
    )
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", selected.entity_id, sketch.sketch_id),
            DrawingObjectRef("datum", datum.datum_id),
        ),
    )
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    token = uuid4().hex
    payload = decode_collection_clipboard(
        encode_collection_clipboard(
            capture_collection_clipboard(session.snapshot, group.members, source_token=token)
        )
    )
    same = session.preview_operation(
        prepare_collection_paste(
            payload,
            session.snapshot,
            (5, 0),
            preserve_external=True,
        )
    )
    copied = same.datums[-1]
    assert copied.attachment == datum.attachment and copied.target_mm == datum.target_mm
    assert copied.position_mm == (7, 2)
    cross = session.preview_operation(
        prepare_collection_paste(
            payload,
            session.snapshot,
            (5, 0),
            preserve_external=False,
        )
    )
    assert cross.datums[-1].attachment is None
    assert cross.datums[-1].target_mm == (5, 0)
    changed = replace(sketch, entities=(replace(external, end_mm=(12, 0)), selected))
    stale = replace(session.snapshot, sketches=(changed,))
    with pytest.raises(ValidationError, match="关联|变化"):
        prepare_collection_paste(payload, stale, (5, 0), preserve_external=True)


@pytest.mark.parametrize("target_kind", ["frame", "reference_dimension", "sketch_dimension"])
def test_group_clipboard_external_annotation_target_is_preserved_or_detached(
    target_kind: str,
) -> None:
    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.drawing_collection_clipboard import (
        capture_collection_clipboard,
        decode_collection_clipboard,
        encode_collection_clipboard,
        prepare_collection_paste,
    )
    from mycad.core.exceptions import ValidationError
    from mycad.core.geometric_tolerance import (
        AnnotationAttachment,
        DatumIdentifier,
        FeatureControlFrame,
        ToleranceRow,
    )
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    unrelated = LineEntity(uuid4().hex, (0, 30), (10, 30))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        position_mm=(5, 2),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, unrelated), (dimension,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, sketch.to_mapping(version=3), "local"),
        session_identity=1,
    )
    if target_kind == "frame":
        frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("position", 0.1, 2),), (0, 5))
        session.stage(
            ReplayAppend(
                "drawing.tolerance.batch", 28, {"add_frames": [frame.to_mapping()]}, "local"
            )
        )
        attachment = AnnotationAttachment("frame", frame.frame_id, (2, 0))
        target_point = (2, 5)
    elif target_kind == "reference_dimension":
        reference = DetachedDimension(uuid4().hex, "aligned", (0, 0), (10, 0), (0, 5), 0, 10)
        session.stage(
            ReplayAppend(
                "drawing.reference_dimensions.batch", 10, {"add": [reference.to_mapping()]}, "local"
            )
        )
        attachment = AnnotationAttachment("reference_dimension", reference.dimension_id, (2, 0))
        target_point = (2, 5)
    else:
        attachment = AnnotationAttachment(
            "sketch_dimension", dimension.constraint_id, (0, 0), sketch.sketch_id
        )
        target_point = (5, 2)
    datum = DatumIdentifier(
        uuid4().hex, "A", (20, 20), target_point, annotation_attachment=attachment
    )
    session.stage(
        ReplayAppend("drawing.tolerance.batch", 28, {"add_datums": [datum.to_mapping()]}, "local")
    )
    group = DrawingGroup(uuid4().hex, (DrawingObjectRef("datum", datum.datum_id),))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    payload = decode_collection_clipboard(
        encode_collection_clipboard(
            capture_collection_clipboard(session.snapshot, group.members, source_token=uuid4().hex)
        )
    )
    if target_kind == "sketch_dimension":
        changed = replace(sketch, entities=(line, replace(unrelated, end_mm=(12, 30))))
        unrelated_change = replace(session.snapshot, sketches=(changed,))
        prepare_collection_paste(payload, unrelated_change, (5, 0), preserve_external=True)
        referenced_change = replace(
            session.snapshot,
            sketches=(replace(sketch, entities=(replace(line, end_mm=(12, 0)), unrelated)),),
        )
        with pytest.raises(ValidationError, match="关联|变化"):
            prepare_collection_paste(payload, referenced_change, (5, 0), preserve_external=True)
    same = session.preview_operation(
        prepare_collection_paste(
            payload,
            session.snapshot,
            (5, 0),
            preserve_external=True,
        )
    )
    assert same.datums[-1].annotation_attachment == attachment
    assert same.datums[-1].target_mm == target_point
    cross = session.preview_operation(
        prepare_collection_paste(
            payload,
            session.snapshot,
            (5, 0),
            preserve_external=False,
        )
    )
    assert cross.datums[-1].annotation_attachment is None
    assert cross.datums[-1].target_mm == (target_point[0] + 5, target_point[1])
