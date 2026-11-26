# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""DXF collection import is one replayable, isolated document operation."""

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import ezdxf
import pytest

from mycad import app
from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
from mycad.core.persistence import save_document
from mycad.core.replay_proposal import ReplayChangeSet
from mycad.core.sketch import LineEntity
from mycad.formats.dxf_collection_import import prepare_dxf_collection_import
from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketches_dxf


def test_external_native_edits_reimport_without_overwriting_existing_blocks(tmp_path: Path) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    outer = LineEntity(uuid4().hex, (0, 0), (2, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (outer,))
    inner = LineEntity(uuid4().hex, (0, 0), (3, 0))
    definition = BlockDefinition(uuid4().hex, "Editable", (inner,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 5))
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", outer.entity_id, sketch.sketch_id),
            DrawingObjectRef("block_instance", instance.instance_id),
        ),
        name="EditedGroup",
    )
    path = tmp_path / "edited-native.dxf"
    write_sketches_dxf(
        (sketch,),
        path,
        groups=(group,),
        block_definitions=(definition,),
        block_instances=(instance,),
    )
    document = cast("Callable[..., Any]", vars(ezdxf)["readfile"])(path)
    layout = document.blocks.get("Editable")
    native_group = document.groups.get("EditedGroup")
    assert layout is not None and native_group is not None
    next(item for item in layout if item.dxftype() == "LINE").dxf.end = (7, 0, 0)
    model = tuple(document.modelspace())
    native_line = next(item for item in model if item.dxftype() == "LINE")
    next(item for item in model if item.dxftype() == "INSERT").dxf.insert = (12, 8, 0)
    native_group.set_data((native_line,))
    document.saveas(path)
    imported = read_sketch_dxf(path)
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    existing = BlockDefinition(uuid4().hex, "Editable", (inner,), ())
    loaded.bus.execute("drawing.block.create", existing.to_mapping(), "local")
    before = app.drawing_collection_snapshot(services)
    first = prepare_dxf_collection_import(imported, before)
    assert any("块名称冲突" in warning for warning in first.warnings)
    loaded.bus.execute(first.operation.command_id, first.operation.params, "local", version=1)
    once = app.drawing_collection_snapshot(services)
    assert once.block_definitions[0] == existing and len(once.block_definitions) == 2
    edited = once.block_definitions[1]
    edited_line = edited.entities[0]
    assert isinstance(edited_line, LineEntity) and edited_line.end_mm == (7, 0)
    assert once.block_instances[0].insertion_mm == (12, 8)
    assert len(once.groups) == 1 and tuple(ref.kind for ref in once.groups[0].members) == (
        "geometry",
    )
    again = prepare_dxf_collection_import(imported, once)
    assert any("块名称冲突" in warning for warning in again.warnings)
    assert any("组名称冲突" in warning for warning in again.warnings)
    loaded.bus.execute(again.operation.command_id, again.operation.params, "local", version=1)
    twice = app.drawing_collection_snapshot(services)
    assert len(twice.block_definitions) == 3 and len(twice.block_instances) == 2
    assert len({item.definition_id for item in twice.block_definitions}) == 3
    assert len({item.instance_id for item in twice.block_instances}) == 2
    second_line = twice.block_definitions[2].entities[0]
    assert isinstance(second_line, LineEntity) and second_line.end_mm == (7, 0)
    assert [item.definition_id for item in twice.block_instances] == [
        twice.block_definitions[1].definition_id,
        twice.block_definitions[2].definition_id,
    ]
    assert twice.block_instances[1].insertion_mm == (12, 8)
    assert len(twice.groups) == 2 and twice.groups[0] != twice.groups[1]
    assert all(tuple(ref.kind for ref in item.members) == ("geometry",) for item in twice.groups)
    assert len({item.members[0].object_id for item in twice.groups}) == 2
    for imported_group in twice.groups:
        ref = imported_group.members[0]
        owner = next(item for item in twice.sketches if item.sketch_id == ref.sketch_id)
        assert any(item.entity_id == ref.object_id for item in owner.entities)
    assert twice.block_definitions[0] == existing and twice.block_definitions[1] == edited
    save = tmp_path / "edited-native.my2d"
    save_document(loaded.document, save)
    reopened = app.open_app_document(services, save)
    assert app.drawing_collection_snapshot(services) == twice
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == once
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.redo_operation()
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == twice


@pytest.mark.parametrize("restriction", ["locked", "frozen", "hidden"])
def test_import_grouped_block_on_new_restricted_layer_preserves_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, restriction: str
) -> None:
    from mycad.core.drawing_text import DrawingText
    from mycad.core.exceptions import ValidationError
    from mycad.core.sketch_layers import SketchLayerTable
    from mycad.formats.dxf_preview import prepare_dxf_output_preview

    document = cast("Callable[..., Any]", vars(ezdxf)["new"])("R2010", units=4)
    layer = document.layers.new("Protected")
    if restriction == "locked":
        layer.lock()
    elif restriction == "frozen":
        layer.freeze()
    else:
        layer.off()
    block = document.blocks.new("Restricted")
    block.add_line((0, 0), (2, 0))
    insert = document.modelspace().add_blockref(
        "Restricted", (5, 5), dxfattribs={"layer": "Protected"}
    )
    document.groups.new("RestrictedGroup").set_data((insert,))
    path = tmp_path / "restricted-layer.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert len(imported.block_instances) == len(imported.groups) == 1
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    previous_text = DrawingText(uuid4().hex, "Prior", (0, 0))
    if restriction == "locked":
        loaded.bus.execute("drawing.text.add", previous_text.to_mapping(), "local")
        loaded.bus.undo_operation()
    before = app.drawing_collection_snapshot(services)
    prepared = prepare_dxf_collection_import(imported, before)
    if restriction == "locked":
        original = cast("Callable[..., None]", vars(type(services.kernel))["_set_drawing_layers"])

        def fail_final(kernel: object, params: Mapping[str, object]) -> None:
            table = SketchLayerTable.from_mapping(params["layers"])
            try:
                target_layer = table.get("Protected")
            except KeyError:
                target_layer = None
            if target_layer is not None and target_layer.locked:
                raise ValidationError("simulated final layer failure")
            original(kernel, params)

        with monkeypatch.context() as failure:
            failure.setattr(type(services.kernel), "_set_drawing_layers", fail_final)
            with pytest.raises(ValidationError, match="simulated final layer failure"):
                loaded.bus.execute(
                    prepared.operation.command_id, prepared.operation.params, "local", version=1
                )
        assert app.drawing_collection_snapshot(services) == before
        assert not loaded.document.commands
        loaded.bus.redo_operation()
        assert services.kernel.drawing_texts == (previous_text,)
        loaded.bus.undo_operation()
        assert app.drawing_collection_snapshot(services) == before
    loaded.bus.execute(prepared.operation.command_id, prepared.operation.params, "local", version=1)
    after = app.drawing_collection_snapshot(services)
    assert len(after.block_instances) == len(after.groups) == 1
    assert after.groups[0].members == (
        DrawingObjectRef("block_instance", after.block_instances[0].instance_id),
    )
    protected = after.layers.get("Protected")
    assert protected.locked == (restriction == "locked")
    assert protected.frozen == (restriction == "frozen")
    assert protected.visible == (restriction != "hidden")
    preview = prepare_dxf_output_preview(services.kernel)
    exported = tmp_path / "restricted-preview.dxf"
    exported.write_bytes(preview.dxf_bytes)
    restored = read_sketch_dxf(exported)
    assert len(restored.groups) == len(restored.block_instances) == 1
    assert restored.groups[0].members == (
        DrawingObjectRef("block_instance", restored.block_instances[0].instance_id),
    )
    restored_layer = restored.sketch.layers.get("Protected")
    assert (restored_layer.locked, restored_layer.frozen, restored_layer.visible) == (
        protected.locked,
        protected.frozen,
        protected.visible,
    )
    if restriction in {"frozen", "hidden"}:
        assert any("没有可见图元" in notice for notice in preview.notices)
    saved = tmp_path / "restricted.my2d"
    save_document(loaded.document, saved)
    reopened = app.open_app_document(services, saved)
    assert app.drawing_collection_snapshot(services) == after
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == after


@pytest.mark.parametrize("restriction", ["locked", "frozen", "hidden"])
def test_dxf_import_remaps_existing_restricted_target_layer(
    tmp_path: Path, restriction: str
) -> None:
    from mycad.core.sketch_layers import SketchLayer

    document = cast("Callable[..., Any]", vars(ezdxf)["new"])("R2010", units=4)
    document.layers.new("Protected")
    block = document.blocks.new("Restricted")
    block.add_line((0, 0), (2, 0))
    document.modelspace().add_blockref("Restricted", (5, 5), dxfattribs={"layer": "Protected"})
    path = tmp_path / "existing-layer.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    target = app.drawing_collection_snapshot(services)
    target_layer = SketchLayer(
        "Protected",
        locked=restriction == "locked",
        frozen=restriction == "frozen",
        visible=restriction != "hidden",
    )
    layers = target.layers.add(target_layer)
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": layers.to_mapping(), "dimension_layer": target.dimension_layer},
        "local",
        version=1,
    )
    before = app.drawing_collection_snapshot(services)
    history = tuple(loaded.document.commands)
    prepared = prepare_dxf_collection_import(imported, before)
    assert any("图层" in message and "Protected" in message for message in prepared.warnings)
    loaded.bus.execute(prepared.operation.command_id, prepared.operation.params, "local", version=1)
    after = app.drawing_collection_snapshot(services)
    assert after.layers.get("Protected") == target_layer
    instance = after.block_instances[0]
    assert instance.layer_name.casefold() != "protected"
    assert not after.layers.get(instance.layer_name).locked
    loaded.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    assert tuple(loaded.document.commands) == history


@pytest.mark.parametrize("restriction", ["visible", "locked", "frozen", "hidden"])
def test_dxf_import_preserves_source_layer_when_existing_layer_differs(
    tmp_path: Path, restriction: str
) -> None:
    from mycad.core.sketch_layers import SketchLayer

    document = cast("Callable[..., Any]", vars(ezdxf)["new"])("R2010", units=4)
    source_layer = document.layers.new("Detail", dxfattribs={"color": 1})
    if restriction == "locked":
        source_layer.lock()
    elif restriction == "frozen":
        source_layer.freeze()
    elif restriction == "hidden":
        source_layer.off()
    block = document.blocks.new("SourceStyle")
    block.add_line((0, 0), (2, 0))
    document.modelspace().add_blockref("SourceStyle", (5, 5), dxfattribs={"layer": "Detail"})
    path = tmp_path / "layer-conflict.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    initial = app.drawing_collection_snapshot(services)
    target_layer = SketchLayer("Detail", color_rgb=(0, 0, 255))
    target_layers = initial.layers.add(target_layer)
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": target_layers.to_mapping(), "dimension_layer": initial.dimension_layer},
        "local",
        version=1,
    )
    before = app.drawing_collection_snapshot(services)
    prepared = prepare_dxf_collection_import(imported, before)
    assert any("图层名称冲突" in item and "Detail" in item for item in prepared.warnings)
    loaded.bus.execute(prepared.operation.command_id, prepared.operation.params, "local", version=1)
    result = app.drawing_collection_snapshot(services)
    assert result.layers.get("Detail") == target_layer
    instance = result.block_instances[0]
    assert instance.layer_name != "Detail"
    source = imported.sketch.layers.get("Detail")
    restored = result.layers.get(instance.layer_name)
    assert restored.color_rgb == source.color_rgb
    assert (restored.locked, restored.frozen, restored.visible) == (
        source.locked,
        source.frozen,
        source.visible,
    )
    loaded.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before


def test_dxf_import_reuses_matching_editable_target_layer(tmp_path: Path) -> None:
    document = cast("Callable[..., Any]", vars(ezdxf)["new"])("R2010", units=4)
    document.layers.new("Detail", dxfattribs={"color": 1})
    block = document.blocks.new("MatchingLayer")
    block.add_line((0, 0), (2, 0))
    document.modelspace().add_blockref("MatchingLayer", (5, 5), dxfattribs={"layer": "Detail"})
    path = tmp_path / "matching-layer.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    target = app.drawing_collection_snapshot(services)
    source_layer = imported.sketch.layers.get("Detail")
    layers = target.layers.add(source_layer)
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": layers.to_mapping(), "dimension_layer": target.dimension_layer},
        "local",
        version=1,
    )
    before = app.drawing_collection_snapshot(services)
    prepared = prepare_dxf_collection_import(imported, before)
    assert not any("图层" in item for item in prepared.warnings)
    loaded.bus.execute(prepared.operation.command_id, prepared.operation.params, "local", version=1)
    result = app.drawing_collection_snapshot(services)
    assert result.layers == before.layers and result.block_instances[0].layer_name == "Detail"
    loaded.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before


def test_repeated_dxf_import_remaps_restricted_layers_for_all_group_members(tmp_path: Path) -> None:
    document = cast("Callable[..., Any]", vars(ezdxf)["new"])("R2010", units=4)
    document.layers.new("Protected").lock()
    block = document.blocks.new("MixedRestricted")
    block.add_line((0, 0), (2, 0))
    block.add_text("Inside", dxfattribs={"layer": "Protected", "height": 2.5})
    model = document.modelspace()
    instance = model.add_blockref("MixedRestricted", (5, 5), dxfattribs={"layer": "Protected"})
    line = model.add_line((0, 0), (3, 0), dxfattribs={"layer": "Protected"})
    text = model.add_text("Outside", dxfattribs={"layer": "Protected", "height": 2.5})
    document.groups.new("MixedGroup").set_data((instance, line, text))
    path = tmp_path / "mixed-restricted.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    before = app.drawing_collection_snapshot(services)
    first_op = prepare_dxf_collection_import(imported, before)
    loaded.bus.execute(first_op.operation.command_id, first_op.operation.params, "local", version=1)
    first = app.drawing_collection_snapshot(services)
    second_op = prepare_dxf_collection_import(imported, first)
    assert any("目标图层受限" in message for message in second_op.warnings)
    loaded.bus.execute(
        second_op.operation.command_id, second_op.operation.params, "local", version=1
    )
    second = app.drawing_collection_snapshot(services)
    assert len(second.groups) == len(second.block_instances) == len(second.block_definitions) == 2
    copied = second.block_instances[1]
    renamed = copied.layer_name
    assert renamed != "Protected" and second.layers.get(renamed).locked
    assert second.layers.get("Protected").locked
    definition = next(
        item for item in second.block_definitions if item.definition_id == copied.definition_id
    )
    assert definition.entities[0].layer_name == "0" and definition.texts[0].layer_name == renamed
    group = second.groups[1]
    geometry_ref = next(item for item in group.members if item.kind == "geometry")
    text_ref = next(item for item in group.members if item.kind == "text")
    sketch = next(item for item in second.sketches if item.sketch_id == geometry_ref.sketch_id)
    assert (
        next(
            item for item in sketch.entities if item.entity_id == geometry_ref.object_id
        ).layer_name
        == renamed
    )
    assert (
        next(item for item in second.texts if item.text_id == text_ref.object_id).layer_name
        == renamed
    )
    assert DrawingObjectRef("block_instance", copied.instance_id) in group.members
    save = tmp_path / "mixed-restricted.my2d"
    save_document(loaded.document, save)
    reopened = app.open_app_document(services, save)
    assert app.drawing_collection_snapshot(services) == second
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == first
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == second


@pytest.mark.parametrize("conflict", ["locked", "color"])
def test_dxf_import_remaps_zero_layer_without_changing_block_inheritance(
    tmp_path: Path, conflict: str
) -> None:
    from dataclasses import replace

    document = cast("Callable[..., Any]", vars(ezdxf)["new"])("R2010", units=4)
    block = document.blocks.new("ZeroInheritance")
    block.add_line((0, 0), (2, 0))
    document.modelspace().add_blockref("ZeroInheritance", (5, 5))
    path = tmp_path / "zero-layer.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    initial = app.drawing_collection_snapshot(services)
    target_zero = (
        replace(initial.layers.get("0"), locked=True)
        if conflict == "locked"
        else replace(initial.layers.get("0"), color_rgb=(0, 0, 255))
    )
    layers = initial.layers.replace(target_zero)
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": layers.to_mapping(), "dimension_layer": initial.dimension_layer},
        "local",
        version=1,
    )
    before = app.drawing_collection_snapshot(services)
    prepared = prepare_dxf_collection_import(imported, before)
    assert any("0 →" in message for message in prepared.warnings)
    loaded.bus.execute(prepared.operation.command_id, prepared.operation.params, "local", version=1)
    after = app.drawing_collection_snapshot(services)
    instance = after.block_instances[0]
    assert instance.layer_name != "0" and not after.layers.get(instance.layer_name).locked
    assert after.layers.get("0") == target_zero
    assert after.block_definitions[0].entities[0].layer_name == "0"
    loaded.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before


def test_dxf_layer_remap_preserves_grouped_dimensions_and_annotations(tmp_path: Path) -> None:
    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.geometric_tolerance import (
        DatumAttachment,
        DatumIdentifier,
        FeatureControlFrame,
        ToleranceRow,
    )
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable

    layers = SketchLayerTable().add(SketchLayer("Protected"))
    line = LineEntity(uuid4().hex, (0, 0), (10, 0), layer_name="Protected")
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        layer_name="Protected",
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,), layers)
    reference = DetachedDimension(
        uuid4().hex, "rotated", (0, 0), (10, 0), (0, 5), 0, 10, layer_name="Protected"
    )
    attachment = DatumAttachment(sketch.sketch_id, SketchGeometryReference(line.entity_id, "start"))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (10, 10),
        layer_name="Protected",
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -3),
        leader_attachment=attachment,
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 10),
        (0, 0),
        layer_name="Protected",
        attachment=attachment,
        layout_mode="shared",
    )
    definition = BlockDefinition(
        uuid4().hex, "AnnotationBlock", (LineEntity(uuid4().hex, (0, 0), (2, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (20, 0), layer_name="Protected")
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),
            DrawingObjectRef("dimension", dimension.constraint_id, sketch.sketch_id),
            DrawingObjectRef("reference_dimension", reference.dimension_id),
            DrawingObjectRef("tolerance", frame.frame_id),
            DrawingObjectRef("datum", datum.datum_id),
            DrawingObjectRef("block_instance", instance.instance_id),
        ),
        name="MixedAnnotations",
    )
    path = tmp_path / "restricted-annotations.dxf"
    write_sketches_dxf(
        (sketch,),
        path,
        drawing_layers=layers,
        reference_dimensions=(reference,),
        tolerance_frames=(frame,),
        datum_identifiers=(datum,),
        block_definitions=(definition,),
        block_instances=(instance,),
        groups=(group,),
    )
    imported = read_sketch_dxf(path)
    assert len(imported.groups) == 1 and len(imported.groups[0].members) == 6
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    target = app.drawing_collection_snapshot(services)
    locked = target.layers.add(SketchLayer("Protected", locked=True))
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": locked.to_mapping(), "dimension_layer": target.dimension_layer},
        "local",
        version=1,
    )
    before = app.drawing_collection_snapshot(services)
    prepared = prepare_dxf_collection_import(imported, before)
    assert any("目标图层受限" in item for item in prepared.warnings)
    loaded.bus.execute(prepared.operation.command_id, prepared.operation.params, "local", version=1)
    result = app.drawing_collection_snapshot(services)
    assert result.layers.get("Protected").locked
    group = result.groups[0]
    refs = {item.kind: item for item in group.members}
    assert set(refs) == {
        "geometry",
        "dimension",
        "reference_dimension",
        "tolerance",
        "datum",
        "block_instance",
    }
    restored = next(
        item for item in result.sketches if item.sketch_id == refs["geometry"].sketch_id
    )
    renamed = restored.entities[0].layer_name
    assert renamed != "Protected" and not result.layers.get(renamed).locked
    assert restored.constraints[0].layer_name == renamed
    assert restored.constraints[0].references[0].entity_id == refs["geometry"].object_id
    assert result.reference_dimensions[0].layer_name == result.frames[0].layer_name == renamed
    assert result.datums[0].layer_name == result.block_instances[0].layer_name == renamed
    datum_attachment = result.datums[0].attachment
    frame_attachment = result.frames[0].leader_attachment
    assert datum_attachment is not None and frame_attachment is not None
    assert datum_attachment.sketch_id == frame_attachment.sketch_id == restored.sketch_id
    assert (
        datum_attachment.reference.entity_id
        == frame_attachment.reference.entity_id
        == restored.entities[0].entity_id
    )
    assert result.block_definitions[0].entities[0].layer_name == "0"
    save = tmp_path / "restricted-annotations.my2d"
    save_document(loaded.document, save)
    reopened = app.open_app_document(services, save)
    assert app.drawing_collection_snapshot(services) == result
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == result


def test_pure_block_import_candidate_repeated_and_reopen_undo(tmp_path: Path) -> None:
    definition = BlockDefinition(
        uuid4().hex, "Symbol", (LineEntity(uuid4().hex, (0, 0), (2, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 8), 45, 2)
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("block_instance", instance.instance_id),), name="Group"
    )
    path = tmp_path / "source.dxf"
    write_sketches_dxf(
        (), path, block_definitions=(definition,), block_instances=(instance,), groups=(group,)
    )
    imported = read_sketch_dxf(path)
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    before = app.drawing_collection_snapshot(services)
    prepared = prepare_dxf_collection_import(imported, before)
    candidate = app.create_replay_candidate(services, loaded, session_identity=1)
    candidate.stage(
        ReplayChangeSet((), (prepared.operation,), False, target_archive_version=8),
        current_session_identity=1,
    )
    preview = candidate.preview(current_session_identity=1)
    assert preview.state == "succeeded" and loaded.document.commands == ()
    grant = candidate.authorize_commit(current_session_identity=1)
    candidate.commit(grant, current_session_identity=1)
    first = app.drawing_collection_snapshot(services)
    assert len(first.block_definitions) == len(first.block_instances) == len(first.groups) == 1
    assert first.groups[0].members == (
        DrawingObjectRef("block_instance", first.block_instances[0].instance_id),
    )
    second_op = prepare_dxf_collection_import(imported, first)
    assert second_op.warnings and any("Symbol" in warning for warning in second_op.warnings)
    loaded.bus.execute(
        second_op.operation.command_id, second_op.operation.params, "local", version=1
    )
    second = app.drawing_collection_snapshot(services)
    assert len(second.block_definitions) == len(second.block_instances) == len(second.groups) == 2
    assert second.block_definitions[0].name != second.block_definitions[1].name
    assert second.block_instances[0].instance_id != second.block_instances[1].instance_id
    save = tmp_path / "imported.my2d"
    save_document(loaded.document, save)
    reopened = app.open_app_document(services, save)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == first
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before


def test_repeated_dxf_block_curve_import_allocates_distinct_point_ids(tmp_path: Path) -> None:
    from mycad.core.sketch import PolylineEntity

    curve = PolylineEntity(uuid4().hex, ((0, 0), (2, 0), (2, 2)))
    definition = BlockDefinition(uuid4().hex, "Curve", (curve,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 5))
    path = tmp_path / "curve.dxf"
    write_sketches_dxf((), path, block_definitions=(definition,), block_instances=(instance,))
    imported = read_sketch_dxf(path)
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    for _ in range(2):
        prepared = prepare_dxf_collection_import(
            imported, app.drawing_collection_snapshot(services)
        )
        loaded.bus.execute(
            prepared.operation.command_id, prepared.operation.params, "local", version=1
        )
    first, second = (item.entities[0] for item in services.kernel.drawing_block_definitions)
    assert isinstance(first, PolylineEntity) and isinstance(second, PolylineEntity)
    assert len(first.point_ids) == len(second.point_ids) == 3
    assert set(first.point_ids).isdisjoint(second.point_ids)
    save = tmp_path / "curve-import.my2d"
    save_document(loaded.document, save)
    reopened = app.open_app_document(services, save)
    assert tuple(item.entities[0] for item in services.kernel.drawing_block_definitions) == (
        first,
        second,
    )
    reopened.bus.undo_operation()
    assert services.kernel.drawing_block_definitions[0].entities == (first,)


def test_mixed_group_import_remaps_geometry_and_text_without_losing_members(tmp_path: Path) -> None:
    from mycad.core.drawing_text import DrawingText
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    text = DrawingText(uuid4().hex, "Label", (1, 2))
    definition = BlockDefinition(
        uuid4().hex, "Mixed", (LineEntity(uuid4().hex, (0, 0), (1, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (4, 5))
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),
            DrawingObjectRef("text", text.text_id),
            DrawingObjectRef("block_instance", instance.instance_id),
        ),
        name="MixedGroup",
    )
    path = tmp_path / "mixed.dxf"
    write_sketches_dxf(
        (sketch,),
        path,
        texts=(text,),
        block_definitions=(definition,),
        block_instances=(instance,),
        groups=(group,),
    )
    imported = read_sketch_dxf(path)
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    before = app.drawing_collection_snapshot(services)
    prepared = prepare_dxf_collection_import(imported, before)
    loaded.bus.execute(prepared.operation.command_id, prepared.operation.params, "local", version=1)
    result = app.drawing_collection_snapshot(services)
    assert (
        len(result.sketches)
        == len(result.texts)
        == len(result.block_instances)
        == len(result.groups)
        == 1
    )
    refs = set(result.groups[0].members)
    assert refs == {
        DrawingObjectRef(
            "geometry", result.sketches[0].entities[0].entity_id, result.sketches[0].sketch_id
        ),
        DrawingObjectRef("text", result.texts[0].text_id),
        DrawingObjectRef("block_instance", result.block_instances[0].instance_id),
    }
    assert result.texts[0].text == "Label"
    loaded.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before


def test_collection_import_preserves_dimension_style_with_block(tmp_path: Path) -> None:
    from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        style_name="Source",
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    style = DimensionStyle("Source", text_height=7)
    definition = BlockDefinition(
        uuid4().hex, "Symbol", (LineEntity(uuid4().hex, (0, 0), (1, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (20, 0))
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),
            DrawingObjectRef("block_instance", instance.instance_id),
        ),
        name="Mixed",
    )
    path = tmp_path / "dimension-block.dxf"
    write_sketches_dxf(
        (sketch,),
        path,
        dimension_styles=DimensionStyleTable((style,), style.name),
        block_definitions=(definition,),
        block_instances=(instance,),
        groups=(group,),
    )
    imported = read_sketch_dxf(path)
    assert imported.dimension_styles
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    operation = prepare_dxf_collection_import(
        imported, app.drawing_collection_snapshot(services)
    ).operation
    loaded.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    result = app.drawing_collection_snapshot(services)
    restored = result.sketches[0].constraints[0]
    assert restored.style_name is not None
    assert result.dimension_styles.get(restored.style_name).text_height == 7
    assert len(result.groups[0].members) == 2 and len(result.block_instances) == 1


def test_collection_import_retains_associated_and_detached_dimension_group(tmp_path: Path) -> None:
    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    constraint = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (constraint,))
    reference = DetachedDimension(uuid4().hex, "rotated", (0, 0), (10, 0), (0, 5), 0, 10)
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),
            DrawingObjectRef("dimension", constraint.constraint_id, sketch.sketch_id),
            DrawingObjectRef("reference_dimension", reference.dimension_id),
        ),
        name="Dimensions",
    )
    path = tmp_path / "dimension-group.dxf"
    write_sketches_dxf((sketch,), path, reference_dimensions=(reference,), groups=(group,))
    imported = read_sketch_dxf(path)
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    before = app.drawing_collection_snapshot(services)
    operation = prepare_dxf_collection_import(imported, before).operation
    loaded.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    result = app.drawing_collection_snapshot(services)
    assert len(result.groups) == len(result.sketches) == len(result.reference_dimensions) == 1
    refs = set(result.groups[0].members)
    assert refs == {
        DrawingObjectRef(
            "geometry", result.sketches[0].entities[0].entity_id, result.sketches[0].sketch_id
        ),
        DrawingObjectRef(
            "dimension",
            result.sketches[0].constraints[0].constraint_id,
            result.sketches[0].sketch_id,
        ),
        DrawingObjectRef("reference_dimension", result.reference_dimensions[0].dimension_id),
    }
    loaded.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before


def test_collection_import_remaps_grouped_frame_and_datum(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier, FeatureControlFrame, ToleranceRow

    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (10, 10),
        leader_target_mm=(0, 0),
        leader_offsets=((-5, -5),),
        leader_anchor_offset=(0, -3),
    )
    datum = DatumIdentifier(uuid4().hex, "A", (20, 10), (16, 0), layout_mode="shared")
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("tolerance", frame.frame_id), DrawingObjectRef("datum", datum.datum_id)),
        name="Annotations",
    )
    path = tmp_path / "annotations.dxf"
    write_sketches_dxf(
        (), path, tolerance_frames=(frame,), datum_identifiers=(datum,), groups=(group,)
    )
    imported = read_sketch_dxf(path)
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    before = app.drawing_collection_snapshot(services)
    operation = prepare_dxf_collection_import(imported, before).operation
    loaded.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    result = app.drawing_collection_snapshot(services)
    assert len(result.groups) == len(result.frames) == len(result.datums) == 1
    assert set(result.groups[0].members) == {
        DrawingObjectRef("tolerance", result.frames[0].frame_id),
        DrawingObjectRef("datum", result.datums[0].datum_id),
    }
    assert (
        result.frames[0].frame_id != frame.frame_id and result.datums[0].datum_id != datum.datum_id
    )
    loaded.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before


def test_unreferenced_definition_imports_and_survives_reopen(tmp_path: Path) -> None:
    from mycad.core.drawing_text import DrawingText

    definition = BlockDefinition(
        uuid4().hex,
        "Standalone",
        (LineEntity(uuid4().hex, (0, 0), (2, 0)),),
        (DrawingText(uuid4().hex, "Label", (1, 1)),),
    )
    path = tmp_path / "definition-only.dxf"
    write_sketches_dxf((), path, block_definitions=(definition,))
    imported = read_sketch_dxf(path)
    assert len(imported.block_definitions) == 1 and imported.block_instances == ()
    assert not any("没有可导入" in item for item in imported.report.warnings)
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    before = app.drawing_collection_snapshot(services)
    operation = prepare_dxf_collection_import(imported, before).operation
    loaded.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    result = app.drawing_collection_snapshot(services)
    assert len(result.block_definitions) == 1 and result.block_instances == ()
    assert (
        result.block_definitions[0].name == "Standalone"
        and result.block_definitions[0].texts[0].text == "Label"
    )
    save = tmp_path / "definition-only.my2d"
    save_document(loaded.document, save)
    reopened = app.open_app_document(services, save)
    assert app.drawing_collection_snapshot(services) == result
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
