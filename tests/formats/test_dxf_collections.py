# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""DXF collection identity handling and native exchange."""

from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, Protocol, TextIO, cast
from uuid import uuid4

import ezdxf.filemanagement as filemanagement
import pytest

from mycad.core.drawing_groups import DrawingObjectRef
from mycad.core.drawing_text import DrawingText
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.formats.dxf_collections import DxfObjectMap
from mycad.formats.providers.dxf_provider import write_sketches_dxf


class _Attrs(Protocol):
    handle: str
    extrusion: tuple[float, float, float]
    description: str
    selectable: int
    name: str
    insert: tuple[float, float, float]
    rotation: float
    xscale: float
    yscale: float
    end: tuple[float, float, float]
    has_arrowhead: int
    color: int
    layer: str


class _Entity(Protocol):
    dxf: _Attrs

    def dxftype(self) -> str: ...
    def discard_xdata(self, appid: str) -> None: ...


class _Extension(Protocol):
    def add_dictionary(self, name: str) -> object: ...


class _BlockRecord(Protocol):
    def new_extension_dict(self) -> _Extension: ...


class _Spline(Protocol):
    weights: list[float]
    knots: list[float]

    def set_open_uniform(self, control_points: list[tuple[float, float]]) -> None: ...


class _Space(Protocol):
    block_record: _BlockRecord

    def __iter__(self) -> Iterator[_Entity]: ...
    def add_spline(self) -> _Spline: ...
    def add_polyline2d(self, *args: object, **kwargs: object) -> object: ...
    def add_polyline3d(self, *args: object, **kwargs: object) -> object: ...
    def add_line(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        dxfattribs: Mapping[str, object] | None = None,
    ) -> _Entity: ...
    def add_text(self, text: str, *, dxfattribs: Mapping[str, object]) -> _Entity: ...
    def add_circle(
        self, center: tuple[float, float], radius: float, *, dxfattribs: Mapping[str, object]
    ) -> _Entity: ...
    def add_ellipse(
        self,
        center: tuple[float, float],
        *,
        major_axis: tuple[float, float],
        ratio: float,
        start_param: float,
        end_param: float,
    ) -> _Entity: ...
    def add_lwpolyline(
        self, points: Iterable[tuple[float, float]], dxfattribs: Mapping[str, object] | None = None
    ) -> _Entity: ...
    def add_mtext(self, text: str, *, dxfattribs: Mapping[str, object]) -> _Entity: ...
    def add_3dface(self, points: Iterable[tuple[float, float, float]]) -> _Entity: ...
    def add_blockref(
        self,
        name: str,
        insert: tuple[float, float],
        dxfattribs: Mapping[str, object] | None = None,
    ) -> _Entity: ...
    def add_attdef(self, tag: str, *, insert: tuple[float, float]) -> _Entity: ...


class _Group(Protocol):
    dxf: _Attrs

    def __iter__(self) -> Iterator[_Entity]: ...
    def set_data(self, entities: Iterable[_Entity]) -> None: ...
    def handles(self) -> Iterable[str]: ...


class _Groups(Protocol):
    def __iter__(self) -> Iterator[tuple[str, _Group]]: ...
    def new(self, name: str, description: str = "", selectable: bool = True) -> _Group: ...
    def get(self, name: str) -> _Group | None: ...


class _Blocks(Protocol):
    def get(self, name: str) -> _Space | None: ...
    def new(self, name: str, base_point: tuple[float, float, float]) -> _Space: ...


class _Styles(Protocol):
    def new(self, name: str, dxfattribs: Mapping[str, object]) -> object: ...


class _Layer(Protocol):
    transparency: float
    dxf: _Attrs


class _Layers(Protocol):
    def new(self, name: str) -> _Layer: ...
    def get(self, name: str) -> _Layer: ...


class _Drawing(Protocol):
    groups: _Groups
    blocks: _Blocks
    styles: _Styles
    layers: _Layers

    def modelspace(self) -> _Space: ...
    def saveas(self, path: Path) -> None: ...


_readfile = cast("Callable[[Path], _Drawing]", vars(filemanagement)["readfile"])
_new = cast("Callable[..., _Drawing]", vars(filemanagement)["new"])
_read = cast("Callable[[TextIO], _Drawing]", vars(filemanagement)["read"])


def test_dxf_object_map_resolves_only_complete_unique_handle_sets() -> None:
    mapping = DxfObjectMap()
    first = DrawingObjectRef("geometry", uuid4().hex, uuid4().hex)
    second = DrawingObjectRef("tolerance", uuid4().hex)
    third = DrawingObjectRef("datum", uuid4().hex)
    mapping.register(first, ("a1",))
    mapping.register(second, ("B2", "b3"))
    assert mapping.handles_for(first) == ("A1",)
    assert mapping.resolve_group(("a1", "B2")) == ((first,), ("B2",))
    assert mapping.resolve_group(("b3", "a1", "b2")) == ((second, first), ())
    mapping.register(third, ("b3",))
    assert mapping.resolve_group(("a1", "b2", "b3", "ff")) == ((first,), ("B2", "B3", "FF"))


def test_dxf_writer_records_actual_geometry_and_text_handles(tmp_path: Path) -> None:
    line = LineEntity(uuid4().hex, (1, 2), (3, 4))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    text = DrawingText(uuid4().hex, "Mapped", (2, 3))
    mapping = DxfObjectMap()
    target = tmp_path / "mapped.dxf"
    write_sketches_dxf((sketch,), target, texts=(text,), object_map=mapping)
    entities = tuple(_readfile(target).modelspace())
    geometry_handle = str(next(item.dxf.handle for item in entities if item.dxftype() == "LINE"))
    text_handle = str(next(item.dxf.handle for item in entities if item.dxftype() == "TEXT"))
    assert mapping.handles_for(DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id)) == (
        geometry_handle,
    )
    assert mapping.handles_for(DrawingObjectRef("text", text.text_id)) == (text_handle,)
    assert mapping.resolve_group((geometry_handle, text_handle))[1] == ()


def test_native_group_export_uses_modelspace_handles_and_reports_missing_members(
    tmp_path: Path,
) -> None:
    from mycad.core.drawing_groups import DrawingGroup

    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    text = DrawingText(uuid4().hex, "Label", (1, 1))
    image = DrawingObjectRef("raster", uuid4().hex)
    line_ref = DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id)
    text_ref = DrawingObjectRef("text", text.text_id)
    group = DrawingGroup(
        uuid4().hex, (line_ref, image, text_ref), name="Mixed", description="Info", selectable=False
    )
    empty = DrawingGroup(uuid4().hex, (DrawingObjectRef("raster", uuid4().hex),), name="Images")
    path = tmp_path / "groups.dxf"
    report = write_sketches_dxf((sketch,), path, texts=(text,), groups=(group, empty))
    doc = _readfile(path)
    native = doc.groups.get("Mixed")
    assert native is not None and native.dxf.description == "Info" and native.dxf.selectable == 0
    assert {item.dxftype() for item in native} == {"LINE", "TEXT"}
    assert doc.groups.get("Images") is None
    assert any("不完整" in warning and "Mixed" in warning for warning in report.warnings)
    assert any("Images" in warning for warning in report.warnings)


def test_native_group_export_reports_unrepresentable_name_and_description(tmp_path: Path) -> None:
    from mycad.core.drawing_groups import DrawingGroup
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),),
        name="组" * 100 + "\n名称",
        description="说明" * 100 + "\n末行",
    )
    path = tmp_path / "group-long-description.dxf"
    report = write_sketches_dxf((sketch,), path, groups=(group,))
    document = _readfile(path)
    name, native = next(iter(document.groups))
    assert len(name.encode("utf-8")) <= 255 and "\n" not in name
    assert len(native.dxf.description.encode("utf-8")) <= 255
    assert "\n" not in native.dxf.description
    assert len(tuple(native)) == 1
    assert any("名称" in warning for warning in report.warnings)
    assert any("说明" in warning for warning in report.warnings)
    assert len(read_sketch_dxf(path).groups[0].members) == 1


def test_native_group_export_renames_sanitized_collisions_and_preserves_members(
    tmp_path: Path,
) -> None:
    from mycad.core.drawing_groups import DrawingGroup
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    lines = (
        LineEntity(uuid4().hex, (0, 0), (1, 0)),
        LineEntity(uuid4().hex, (0, 2), (2, 2)),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    groups = tuple(
        DrawingGroup(
            uuid4().hex,
            (DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),),
            name=name,
            description="first\nsecond",
        )
        for line, name in zip(lines, ("A/B", "A?B"), strict=True)
    )
    paths = (tmp_path / "first.dxf", tmp_path / "second.dxf")
    reports = [write_sketches_dxf((sketch,), path, groups=groups) for path in paths]
    imported = [read_sketch_dxf(path) for path in paths]
    assert [item.name for item in imported[0].groups] == [item.name for item in imported[1].groups]
    assert len({item.name for item in imported[0].groups}) == 2
    assert all(item.description == "first second" for item in imported[0].groups)
    assert all(len(item.members) == 1 for item in imported[0].groups)
    assert all(any("说明" in warning for warning in report.warnings) for report in reports)
    assert all(any("名称" in warning for warning in report.warnings) for report in reports)


def test_native_group_import_maps_actual_entities_without_metadata(tmp_path: Path) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    space = document.modelspace()
    line = space.add_line((1, 2), (3, 4))
    text = space.add_text("Externally changed", dxfattribs={"insert": (7, 8), "height": 2})
    group = document.groups.new("External", description="Description", selectable=False)
    group.set_data((line, text))
    path = tmp_path / "external-group.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert len(result.groups) == 1
    restored = result.groups[0]
    assert (
        restored.name == "External"
        and restored.description == "Description"
        and not restored.selectable
    )
    expected_by_handle = {
        str(line.dxf.handle): DrawingObjectRef(
            "geometry", result.sketch.entities[0].entity_id, result.sketch.sketch_id
        ),
        str(text.dxf.handle): DrawingObjectRef("text", result.texts[0].text_id),
    }
    reread_group = _readfile(path).groups.get("External")
    assert reread_group is not None
    assert restored.members == tuple(
        expected_by_handle[handle] for handle in reread_group.handles()
    )
    assert result.texts[0].text == "Externally changed"


def test_import_group_preserves_supported_members_and_reports_unsupported(tmp_path: Path) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    space = document.modelspace()
    line = space.add_line((0, 0), (2, 0))
    face = space.add_3dface([(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)])
    group = document.groups.new("Partial")
    group.set_data((line, face))
    path = tmp_path / "partial-group.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert len(result.groups) == 1 and len(result.groups[0].members) == 1
    assert result.groups[0].members[0].kind == "geometry"
    assert any("Partial" in warning and "无法" in warning for warning in result.report.warnings)


def test_output_preview_bytes_include_native_groups() -> None:
    import io

    from mycad import app
    from mycad.core.drawing_groups import DrawingGroup
    from mycad.formats.dxf_preview import prepare_dxf_output_preview

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),),
        name="PreviewGroup",
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    preview = prepare_dxf_output_preview(services.kernel)
    native = _read(io.StringIO(preview.dxf_bytes.decode("utf-8")))
    restored = native.groups.get("PreviewGroup")
    assert restored is not None and [item.dxftype() for item in restored] == ["LINE"]


def test_native_block_export_includes_text_instances_and_group(tmp_path: Path) -> None:
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.drawing_groups import DrawingGroup

    entity = LineEntity(uuid4().hex, (0, 0), (2, 0))
    text = DrawingText(uuid4().hex, "Block label", (1, 1))
    definition = BlockDefinition(uuid4().hex, "Part", (entity,), (text,))
    first = BlockInstance(uuid4().hex, definition.definition_id, (4, 5), 30, 2)
    second = BlockInstance(uuid4().hex, definition.definition_id, (10, 12))
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("block_instance", first.instance_id),), name="BlockGroup"
    )
    path = tmp_path / "blocks.dxf"
    report = write_sketches_dxf(
        (), path, block_definitions=(definition,), block_instances=(first, second), groups=(group,)
    )
    document = _readfile(path)
    native = document.blocks.get("Part")
    assert native is not None and {item.dxftype() for item in native} == {"LINE", "TEXT"}
    inserts = tuple(item for item in document.modelspace() if item.dxftype() == "INSERT")
    assert len(inserts) == 2
    native_first = inserts[0]
    assert native_first.dxf.name == "Part"
    assert tuple(native_first.dxf.insert)[:2] == (4, 5)
    assert (
        native_first.dxf.rotation == 30 and native_first.dxf.xscale == native_first.dxf.yscale == 2
    )
    native_group = document.groups.get("BlockGroup")
    assert native_group is not None and [item.dxf.handle for item in native_group] == [
        native_first.dxf.handle
    ]
    assert not any("没有可导出的" in warning or "不完整" in warning for warning in report.warnings)


def test_document_preview_exports_blocks_from_shared_definition() -> None:
    import io

    from mycad import app
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.drawing_groups import DrawingGroup
    from mycad.formats.dxf_preview import prepare_dxf_output_preview

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    definition = BlockDefinition(
        uuid4().hex, "Shared", (LineEntity(uuid4().hex, (0, 0), (3, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (8, 9))
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("block_instance", instance.instance_id),), name="WithBlock"
    )
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    preview = prepare_dxf_output_preview(services.kernel)
    document = _read(io.StringIO(preview.dxf_bytes.decode("utf-8")))
    assert document.blocks.get("Shared") is not None
    group_native = document.groups.get("WithBlock")
    assert group_native is not None and [item.dxftype() for item in group_native] == ["INSERT"]
    assert preview.report.entity_count == 1


def test_block_export_handles_control_characters_long_names_and_collisions(tmp_path: Path) -> None:
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.drawing_groups import DrawingGroup
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    definitions = tuple(
        BlockDefinition(
            uuid4().hex,
            name,
            (LineEntity(uuid4().hex, (0, 0), (index, 0)),),
            (),
        )
        for index, name in enumerate(("A\nB", "A?B", "块" * 100), start=1)
    )
    instances = tuple(
        BlockInstance(uuid4().hex, definition.definition_id, (index * 10, 0))
        for index, definition in enumerate(definitions, start=1)
    )
    group = DrawingGroup(
        uuid4().hex,
        tuple(DrawingObjectRef("block_instance", instance.instance_id) for instance in instances),
        name="Blocks",
    )
    paths = (tmp_path / "names1.dxf", tmp_path / "names2.dxf")
    reports = [
        write_sketches_dxf(
            (), path, block_definitions=definitions, block_instances=instances, groups=(group,)
        )
        for path in paths
    ]
    results = [read_sketch_dxf(path) for path in paths]
    names = [definition.name for definition in results[0].block_definitions]
    assert names == [definition.name for definition in results[1].block_definitions]
    assert len({name.casefold() for name in names}) == 3
    assert all(len(name.encode("utf-8")) <= 255 and "\n" not in name for name in names)
    assert len(results[0].block_instances) == 3 and len(results[0].groups[0].members) == 3
    by_id = {definition.definition_id: definition for definition in results[0].block_definitions}
    assert {ref.object_id for ref in results[0].groups[0].members} == {
        instance.instance_id for instance in results[0].block_instances
    }
    for instance in results[0].block_instances:
        line = by_id[instance.definition_id].entities[0]
        assert isinstance(line, LineEntity) and line.end_mm[0] == instance.insertion_mm[0] / 10
    assert all(
        sum("名称已转换" in warning for warning in report.warnings) == 3 for report in reports
    )


def test_collection_name_conversion_matches_real_preview_and_preserves_document(
    tmp_path: Path,
) -> None:
    from mycad import app
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.drawing_groups import DrawingGroup
    from mycad.formats.dxf_preview import prepare_dxf_output_preview
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    definition = BlockDefinition(
        uuid4().hex, "块\n" + "长" * 100, (LineEntity(uuid4().hex, (0, 0), (5, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (4, 5))
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("block_instance", instance.instance_id),),
        name="组\n" + "长" * 100,
        description="说明\n第二行",
    )
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    before = app.drawing_collection_snapshot(services)
    commands = tuple(loaded.document.commands)
    preview = prepare_dxf_output_preview(services.kernel)
    assert app.drawing_collection_snapshot(services) == before
    assert tuple(loaded.document.commands) == commands
    assert any("块" in warning and "名称已转换" in warning for warning in preview.report.warnings)
    assert any("组" in warning and "名称" in warning for warning in preview.report.warnings)
    assert any("说明" in warning for warning in preview.report.warnings)
    path = tmp_path / "name-conversion-preview.dxf"
    path.write_bytes(preview.dxf_bytes)
    restored = read_sketch_dxf(path)
    assert (
        len(restored.block_definitions)
        == len(restored.block_instances)
        == len(restored.groups)
        == 1
    )
    assert "\n" not in restored.block_definitions[0].name
    assert restored.groups[0].name is not None and "\n" not in restored.groups[0].name
    assert restored.groups[0].description == "说明 第二行"
    assert restored.groups[0].members == (
        DrawingObjectRef("block_instance", restored.block_instances[0].instance_id),
    )


def test_external_native_block_import_respects_base_point_and_transform(tmp_path: Path) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    layout = document.blocks.new("Foreign", base_point=(2, 3, 0))
    layout.add_line((2, 3), (4, 3))
    layout.add_text("Part", dxfattribs={"insert": (3, 4), "height": 2})
    native = document.modelspace().add_blockref(
        "Foreign", (10, 20), dxfattribs={"rotation": 90, "xscale": 2, "yscale": 2, "zscale": 2}
    )
    document.groups.new("NativeGroup").set_data((native,))
    path = tmp_path / "foreign-block.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert len(result.block_definitions) == len(result.block_instances) == 1
    definition, instance = result.block_definitions[0], result.block_instances[0]
    assert definition.name == "Foreign" and len(definition.entities) == len(definition.texts) == 1
    line = definition.entities[0]
    assert isinstance(line, LineEntity) and line.start_mm == (0, 0) and line.end_mm == (2, 0)
    assert definition.texts[0].position_mm == (1, 1)
    assert instance.insertion_mm == (10, 20) and instance.rotation_deg == 90 and instance.scale == 2
    assert result.groups[0].members == (DrawingObjectRef("block_instance", instance.instance_id),)
    assert not any("没有可导入" in warning for warning in result.report.warnings)


def test_cyclic_external_blocks_are_rejected_without_partial_group_import(tmp_path: Path) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    first = document.blocks.new("CycleA", base_point=(0, 0, 0))
    second = document.blocks.new("CycleB", base_point=(0, 0, 0))
    first.add_line((0, 0), (2, 0))
    second.add_line((0, 0), (3, 0))
    first.add_blockref("CycleB", (0, 0))
    second.add_blockref("CycleA", (0, 0))
    good = document.blocks.new("Good", base_point=(0, 0, 0))
    good.add_line((0, 0), (4, 0))
    layout = document.modelspace()
    bad_insert = layout.add_blockref("CycleA", (0, 0))
    good_insert = layout.add_blockref("Good", (10, 0))
    document.groups.new("Mixed").set_data((bad_insert, good_insert))
    path = tmp_path / "cyclic-blocks.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert [item.name for item in imported.block_definitions] == ["Good"]
    assert len(imported.block_instances) == len(imported.groups) == 1
    assert imported.groups[0].members == (
        DrawingObjectRef("block_instance", imported.block_instances[0].instance_id),
    )
    assert any("CycleA" in item and "未导入" in item for item in imported.report.warnings)
    assert any("组" in item and "无法完整" in item for item in imported.report.warnings)


@pytest.mark.parametrize("unsupported", ["nested", "attribute", "nonuniform", "negative"])
def test_external_unsupported_blocks_are_not_partially_imported(
    tmp_path: Path, unsupported: str
) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    layout = document.blocks.new("Rejected", base_point=(0, 0, 0))
    layout.add_line((0, 0), (2, 0))
    if unsupported == "nested":
        nested = document.blocks.new("Nested", base_point=(0, 0, 0))
        nested.add_line((0, 0), (1, 0))
        layout.add_blockref("Nested", (0, 0))
    if unsupported == "attribute":
        layout.add_attdef("TAG", insert=(0, 0))
    params: dict[str, object] = {}
    if unsupported == "nonuniform":
        params = {"xscale": 2, "yscale": 1}
    if unsupported == "negative":
        params = {"xscale": -1, "yscale": -1}
    document.modelspace().add_blockref("Rejected", (4, 5), dxfattribs=params)
    path = tmp_path / f"rejected-{unsupported}.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert result.block_definitions == () and result.block_instances == ()
    assert any("未导入" in item and "Rejected" in item for item in result.report.warnings)


@pytest.mark.parametrize(
    "kind",
    ["oblique", "mirror", "style_oblique", "style_mirror", "style_vertical", "inline", "spacing"],
)
@pytest.mark.parametrize("with_instance", [False, True])
def test_external_block_rejects_lossy_text_without_affecting_other_blocks(
    tmp_path: Path, kind: str, with_instance: bool
) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    bad = document.blocks.new("LossyText", base_point=(0, 0, 0))
    bad.add_line((0, 0), (1, 0))
    if kind == "oblique":
        bad.add_text("BAD", dxfattribs={"insert": (0, 0), "height": 2.5, "oblique": 15})
    elif kind == "mirror":
        bad.add_text("BAD", dxfattribs={"insert": (0, 0), "height": 2.5, "text_generation_flag": 2})
    elif kind in {"style_oblique", "style_mirror", "style_vertical"}:
        attributes = (
            {"font": "txt", "oblique": 15}
            if kind == "style_oblique"
            else {"font": "txt", "generation_flags": 2}
            if kind == "style_mirror"
            else {"font": "txt", "flags": 4}
        )
        document.styles.new("UnsupportedStyle", dxfattribs=attributes)
        bad.add_text(
            "BAD", dxfattribs={"insert": (0, 0), "height": 2.5, "style": "UnsupportedStyle"}
        )
    elif kind == "inline":
        bad.add_mtext(
            r"A\CBAD", dxfattribs={"insert": (0, 0), "char_height": 2.5, "line_spacing_style": 2}
        )
    else:
        bad.add_mtext(
            "BAD", dxfattribs={"insert": (0, 0), "char_height": 2.5, "line_spacing_style": 1}
        )
    if with_instance:
        document.modelspace().add_blockref("LossyText", (0, 0))
    good = document.blocks.new("Good", base_point=(0, 0, 0))
    good.add_line((0, 0), (1, 0))
    document.modelspace().add_blockref("Good", (10, 0))
    path = tmp_path / f"lossy-{kind}-{with_instance}.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert [item.name for item in result.block_definitions] == ["Good"]
    assert len(result.block_instances) == 1
    assert any("LossyText" in warning and "文字" in warning for warning in result.report.warnings)


def test_external_block_accepts_supported_multiline_text(tmp_path: Path) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    block = document.blocks.new("PlainMultiline", base_point=(0, 0, 0))
    block.add_mtext(
        r"First\PSecond",
        dxfattribs={"insert": (2, 3), "char_height": 2.5, "line_spacing_style": 2},
    )
    document.modelspace().add_blockref("PlainMultiline", (10, 0))
    path = tmp_path / "plain-multiline.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert len(result.block_definitions) == len(result.block_instances) == 1
    assert result.block_definitions[0].texts[0].text == "First\nSecond"


@pytest.mark.parametrize(
    "kind",
    [
        "line_thickness",
        "line_invisible",
        "text_thickness",
        "text_invisible",
        "mtext_background",
        "mtext_vertical",
        "insert_invisible",
    ],
)
def test_external_block_rejects_unrepresentable_geometry_and_visibility(
    tmp_path: Path, kind: str
) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    bad = document.blocks.new("InvalidMember", base_point=(0, 0, 0))
    line_attributes: dict[str, object] = {}
    if kind == "line_thickness":
        line_attributes["thickness"] = 2
    elif kind == "line_invisible":
        line_attributes["invisible"] = 1
    bad.add_line((0, 0), (2, 0), dxfattribs=line_attributes)
    if kind.startswith("text_"):
        bad.add_text(
            "Text",
            dxfattribs={"height": 2.5, "thickness" if kind == "text_thickness" else "invisible": 1},
        )
    if kind.startswith("mtext_"):
        attributes: dict[str, object] = {"char_height": 2.5, "line_spacing_style": 2}
        attributes["bg_fill" if kind == "mtext_background" else "flow_direction"] = (
            1 if kind == "mtext_background" else 3
        )
        bad.add_mtext("Text", dxfattribs=attributes)
    document.modelspace().add_blockref(
        "InvalidMember", (0, 0), dxfattribs={"invisible": 1} if kind == "insert_invisible" else {}
    )
    good = document.blocks.new("Good", base_point=(0, 0, 0))
    good.add_line((0, 0), (1, 0))
    document.modelspace().add_blockref("Good", (10, 0))
    path = tmp_path / f"block-{kind}.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert [item.name for item in result.block_definitions] == ["Good"]
    assert len(result.block_instances) == 1
    assert any(
        "InvalidMember" in warning and "未导入" in warning for warning in result.report.warnings
    )


@pytest.mark.parametrize("enabled", [True, False])
def test_external_clipped_block_instance_is_not_silently_imported(
    tmp_path: Path, enabled: bool
) -> None:
    from ezdxf.entities.insert import Insert
    from ezdxf.xclip import XClip

    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    block = document.blocks.new("Clipped", base_point=(0, 0, 0))
    block.add_line((0, 0), (10, 0))
    clipped = document.modelspace().add_blockref("Clipped", (0, 0))
    clip = XClip(cast("Insert", clipped))
    cast("Callable[..., None]", vars(XClip)["set_block_clipping_path"])(clip, ((0, -1), (3, 1)))
    if not enabled:
        clip.disable_clipping()
    normal = document.modelspace().add_blockref("Clipped", (20, 0))
    document.groups.new("Instances").set_data((clipped, normal))
    path = tmp_path / "clipped.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert len(result.block_definitions) == 1
    assert len(result.block_instances) == (1 if enabled else 2)
    if enabled:
        assert result.block_instances[0].insertion_mm == (20, 0)
        assert any("裁剪" in warning and "未导入" in warning for warning in result.report.warnings)
        assert result.groups[0].members == (
            DrawingObjectRef("block_instance", result.block_instances[0].instance_id),
        )
        assert any(
            "Instances" in warning and "无法完整" in warning for warning in result.report.warnings
        )
    else:
        assert len(result.groups[0].members) == 2


@pytest.mark.parametrize(
    ("scope", "attribute", "value"),
    (
        ("member", "color", 1),
        ("member", "true_color", 0x00FF00),
        ("member", "linetype", "DASHED"),
        ("member", "lineweight", 50),
        ("member", "ltscale", 2.0),
        ("member", "transparency", 0x02000080),
        ("instance", "color", 1),
        ("instance", "true_color", 0x00FF00),
        ("instance", "linetype", "DASHED"),
        ("instance", "lineweight", 50),
        ("instance", "ltscale", 2.0),
        ("instance", "transparency", 0x02000080),
    ),
)
def test_external_block_rejects_unrepresentable_object_appearance(
    tmp_path: Path, scope: str, attribute: str, value: object
) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    block = document.blocks.new("Styled", base_point=(0, 0, 0))
    block.add_line((0, 0), (2, 0), dxfattribs={attribute: value} if scope == "member" else {})
    document.modelspace().add_blockref(
        "Styled", (0, 0), dxfattribs={attribute: value} if scope == "instance" else {}
    )
    good = document.blocks.new("Good", base_point=(0, 0, 0))
    good.add_line((0, 0), (1, 0))
    document.modelspace().add_blockref("Good", (10, 0))
    path = tmp_path / f"{scope}-{attribute}.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert [item.name for item in result.block_definitions] == ["Good"]
    assert len(result.block_instances) == 1
    assert any("Styled" in warning and "外观" in warning for warning in result.report.warnings)


@pytest.mark.parametrize("layer", ["0", "Detail"])
def test_block_byblock_appearance_is_only_inherited_from_zero_layer(
    tmp_path: Path, layer: str
) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    document.layers.new("Detail")
    block = document.blocks.new("ByBlock", base_point=(0, 0, 0))
    block.add_line(
        (0, 0),
        (2, 0),
        dxfattribs={"layer": layer, "color": 0, "linetype": "BYBLOCK", "lineweight": -2},
    )
    document.modelspace().add_blockref("ByBlock", (0, 0))
    path = tmp_path / f"byblock-{layer}.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    if layer == "0":
        assert len(result.block_definitions) == len(result.block_instances) == 1
    else:
        assert result.block_definitions == result.block_instances == ()
        assert any("外观" in warning for warning in result.report.warnings)


@pytest.mark.parametrize("location", ["instance", "member", "zero_inherited"])
def test_external_block_checks_effective_layer_transparency(tmp_path: Path, location: str) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    document.layers.new("Transparent").transparency = 0.5
    if location == "zero_inherited":
        document.layers.get("0").transparency = 0.5
        document.layers.new("Opaque")
    block = document.blocks.new("Layered", base_point=(0, 0, 0))
    block.add_line(
        (0, 0), (2, 0), dxfattribs={"layer": "Transparent" if location == "member" else "0"}
    )
    instance_layer = (
        "Transparent"
        if location == "instance"
        else "Opaque"
        if location == "zero_inherited"
        else "0"
    )
    document.modelspace().add_blockref("Layered", (0, 0), dxfattribs={"layer": instance_layer})
    good = document.blocks.new("Good", base_point=(0, 0, 0))
    good.add_line((0, 0), (1, 0))
    document.modelspace().add_blockref(
        "Good", (10, 0), dxfattribs={"layer": "Opaque" if location == "zero_inherited" else "0"}
    )
    path = tmp_path / f"layer-transparency-{location}.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert any("透明" in warning and "图层" in warning for warning in result.report.warnings)
    if location == "zero_inherited":
        assert [item.name for item in result.block_definitions] == ["Layered", "Good"]
        assert len(result.block_instances) == 2
    else:
        assert [item.name for item in result.block_definitions] == ["Good"]
        assert len(result.block_instances) == 1
        assert any("Layered" in warning and "透明" in warning for warning in result.report.warnings)


@pytest.mark.parametrize(
    "kind", ["polyline_elevation", "text_z", "mtext_direction_z", "mtext_direction_nan"]
)
def test_external_block_rejects_nonfinite_plane_coordinates(tmp_path: Path, kind: str) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    bad = document.blocks.new("InvalidPlane", base_point=(0, 0, 0))
    bad.add_line((0, 0), (2, 0))
    if kind == "polyline_elevation":
        bad.add_lwpolyline(((0, 0), (1, 0)), dxfattribs={"elevation": float("nan")})
    elif kind == "text_z":
        bad.add_text("Text", dxfattribs={"height": 2, "insert": (0, 0, float("nan"))})
    else:
        direction = (1, 0, 1) if kind == "mtext_direction_z" else (1, 0, float("nan"))
        bad.add_mtext(
            "Text",
            dxfattribs={"char_height": 2, "line_spacing_style": 2, "text_direction": direction},
        )
    document.modelspace().add_blockref("InvalidPlane", (0, 0))
    good = document.blocks.new("Good", base_point=(0, 0, 0))
    good.add_line((0, 0), (1, 0))
    document.modelspace().add_blockref("Good", (10, 0))
    path = tmp_path / f"{kind}.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert [item.name for item in result.block_definitions] == ["Good"]
    assert len(result.block_instances) == 1
    assert any(
        "InvalidPlane" in warning and "未导入" in warning for warning in result.report.warnings
    )


def test_external_block_rejects_nonfinite_spline_weights(tmp_path: Path) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    bad = document.blocks.new("InvalidSpline", base_point=(0, 0, 0))
    spline = bad.add_spline()
    spline.set_open_uniform([(0, 0), (1, 1), (2, 1), (3, 0)])
    spline.weights = [1.0, float("nan"), 1.0, 1.0]
    document.modelspace().add_blockref("InvalidSpline", (0, 0))
    good = document.blocks.new("Good", base_point=(0, 0, 0))
    good.add_line((0, 0), (1, 0))
    document.modelspace().add_blockref("Good", (10, 0))
    path = tmp_path / "invalid-spline.dxf"
    document.saveas(path)

    result = read_sketch_dxf(path)
    assert [item.name for item in result.block_definitions] == ["Good"]
    assert len(result.block_instances) == 1
    assert any(
        "InvalidSpline" in warning and "未导入" in warning for warning in result.report.warnings
    )


@pytest.mark.parametrize("partial", [True, False])
def test_external_block_requires_complete_spline_weights(tmp_path: Path, partial: bool) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    block = document.blocks.new("Weighted", base_point=(0, 0, 0))
    spline = block.add_spline()
    spline.set_open_uniform([(0, 0), (1, 1), (2, 1), (3, 0)])
    spline.weights = [1.0, 1.0] if partial else [1.0, 1.0, 1.0, 1.0]
    document.modelspace().add_blockref("Weighted", (0, 0))
    good = document.blocks.new("Good", base_point=(0, 0, 0))
    good.add_line((0, 0), (1, 0))
    document.modelspace().add_blockref("Good", (10, 0))
    path = tmp_path / "weighted-spline.dxf"
    document.saveas(path)

    result = read_sketch_dxf(path)
    assert [item.name for item in result.block_definitions] == (
        ["Good"] if partial else ["Weighted", "Good"]
    )
    assert len(result.block_instances) == (1 if partial else 2)
    if partial:
        assert any(
            "Weighted" in warning and "未导入" in warning for warning in result.report.warnings
        )


@pytest.mark.parametrize("target", ["insert", "circle", "polyline", "ellipse", "text", "mtext"])
@pytest.mark.parametrize("magnitude", [0.5, 2.0])
def test_external_block_accepts_positive_nonunit_xy_normal(
    tmp_path: Path, target: str, magnitude: float
) -> None:
    from mycad.core.drawing_blocks import expand_block
    from mycad.core.drawing_text import TextStyleTable
    from mycad.core.sketch import CircleEntity, EllipseEntity, PolylineEntity
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    block = document.blocks.new("NonunitNormal", base_point=(0, 0, 0))
    normal = {"extrusion": (0, 0, magnitude)}
    if target == "circle":
        block.add_circle((1, 2), 1, dxfattribs=normal)
    elif target == "polyline":
        block.add_lwpolyline(((0, 0), (2, 0)), dxfattribs=normal)
    elif target == "ellipse":
        ellipse = block.add_ellipse(
            (1, 2), major_axis=(2, 0), ratio=0.5, start_param=0, end_param=6.283185307179586
        )
        ellipse.dxf.extrusion = (0, 0, magnitude)
    elif target == "text":
        block.add_text("Text", dxfattribs={"height": 2, **normal})
    elif target == "mtext":
        block.add_mtext("Text", dxfattribs={"char_height": 2, "line_spacing_style": 2, **normal})
    else:
        block.add_line((0, 0), (2, 0))
    instance = document.modelspace().add_blockref(
        "NonunitNormal", (5, 4), dxfattribs=normal if target == "insert" else None
    )
    document.groups.new("GROUP").set_data((instance,))
    path = tmp_path / f"nonunit-normal-{target}.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert len(result.block_definitions) == len(result.block_instances) == 1
    assert len(result.groups) == 1 and len(result.groups[0].members) == 1
    assert not any("未导入" in warning for warning in result.report.warnings)
    expanded = expand_block(
        result.block_definitions[0],
        result.block_instances[0],
        result.text_styles or TextStyleTable(),
    )
    if target in {"circle", "ellipse"}:
        assert isinstance(expanded.entities[0], CircleEntity | EllipseEntity)
        assert expanded.entities[0].center_mm == (6, 6)
    elif target == "polyline":
        assert isinstance(expanded.entities[0], PolylineEntity)
        assert expanded.entities[0].points_mm == ((5, 4), (7, 4))
    elif target in {"text", "mtext"}:
        assert expanded.texts[0].position_mm == (5, 4)
    exported = tmp_path / f"roundtrip-{target}-{magnitude}.dxf"
    write_sketches_dxf(
        (),
        exported,
        groups=result.groups,
        block_definitions=result.block_definitions,
        block_instances=result.block_instances,
        text_styles=result.text_styles,
    )
    reimported = read_sketch_dxf(exported)
    assert len(reimported.block_instances) == len(reimported.groups) == 1
    assert reimported.block_instances[0].insertion_mm == (5, 4)


@pytest.mark.parametrize("target", ["insert", "circle", "text"])
def test_external_block_rejects_reverse_xy_normal(tmp_path: Path, target: str) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    block = document.blocks.new("Reverse", base_point=(0, 0, 0))
    normal = {"extrusion": (0, 0, -2)}
    if target == "circle":
        block.add_circle((0, 0), 1, dxfattribs=normal)
    elif target == "text":
        block.add_text("Text", dxfattribs={"height": 2, **normal})
    else:
        block.add_line((0, 0), (2, 0))
    document.modelspace().add_blockref(
        "Reverse", (0, 0), dxfattribs=normal if target == "insert" else None
    )
    path = tmp_path / f"reverse-normal-{target}.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert result.block_definitions == () and result.block_instances == ()
    assert any("Reverse" in warning and "未导入" in warning for warning in result.report.warnings)


@pytest.mark.parametrize("normal", [(0, 0, 0), (0, 0, float("inf")), (1e-12, 0, 2)])
def test_block_normal_rejects_zero_nonfinite_or_tilted_vectors(
    normal: tuple[float, float, float],
) -> None:
    from mycad.formats.dxf_collections import is_exact_positive_xy_normal

    assert not is_exact_positive_xy_normal(normal)


def test_external_block_accepts_planar_mtext_direction(tmp_path: Path) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    block = document.blocks.new("ValidText", base_point=(0, 0, 0))
    block.add_mtext(
        "Text", dxfattribs={"char_height": 2, "line_spacing_style": 2, "text_direction": (0, 1, 0)}
    )
    document.modelspace().add_blockref("ValidText", (0, 0))
    path = tmp_path / "valid-mtext-direction.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert len(result.block_instances) == 1
    assert result.block_definitions[0].texts[0].rotation_deg == pytest.approx(90)


def test_block_native_changes_override_export_metadata(tmp_path: Path) -> None:
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    entity = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Editable", (entity,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 5))
    path = tmp_path / "changed.dxf"
    write_sketches_dxf((), path, block_definitions=(definition,), block_instances=(instance,))
    document = _readfile(path)
    layout = document.blocks.get("Editable")
    assert layout is not None
    native = next(item for item in layout if item.dxftype() == "LINE")
    native.dxf.end = (7, 0, 0)
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert len(imported.block_definitions) == 1
    line = imported.block_definitions[0].entities[0]
    assert isinstance(line, LineEntity) and line.end_mm == (7, 0)


def test_native_block_and_group_edits_override_old_metadata_together(tmp_path: Path) -> None:
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.drawing_groups import DrawingGroup
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

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
    path = tmp_path / "native-edits.dxf"
    write_sketches_dxf(
        (sketch,),
        path,
        groups=(group,),
        block_definitions=(definition,),
        block_instances=(instance,),
    )
    document = _readfile(path)
    layout = document.blocks.get("Editable")
    native_group = document.groups.get("EditedGroup")
    assert layout is not None and native_group is not None
    line = next(item for item in layout if item.dxftype() == "LINE")
    line.dxf.end = (7, 0, 0)
    model = tuple(document.modelspace())
    native_line = next(item for item in model if item.dxftype() == "LINE")
    native_insert = next(item for item in model if item.dxftype() == "INSERT")
    native_insert.dxf.insert = (12, 8, 0)
    native_group.set_data((native_line,))
    document.saveas(path)

    imported = read_sketch_dxf(path)
    assert len(imported.block_definitions) == len(imported.block_instances) == 1
    imported_line = imported.block_definitions[0].entities[0]
    assert isinstance(imported_line, LineEntity) and imported_line.end_mm == (7, 0)
    assert imported.block_instances[0].insertion_mm == (12, 8)
    assert len(imported.groups) == 1
    assert len(imported.groups[0].members) == 1
    assert imported.groups[0].members[0].kind == "geometry"


def test_external_unicode_casefold_collisions_keep_distinct_blocks_and_groups(
    tmp_path: Path,
) -> None:
    from mycad import app
    from mycad.formats.dxf_collection_import import prepare_dxf_collection_import
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    for index, name in enumerate(("Straße", "STRASSE"), start=1):
        block = document.blocks.new(name, base_point=(0, 0, 0))
        block.add_line((0, 0), (index, 0))
        insert = document.modelspace().add_blockref(name, (index * 10, 0))
        document.groups.new(name).set_data((insert,))
    path = tmp_path / "casefold-collisions.dxf"
    document.saveas(path)

    imported = read_sketch_dxf(path)
    assert len(imported.block_definitions) == len(imported.block_instances) == 2
    assert len({item.name.casefold() for item in imported.block_definitions}) == 2
    assert len({item.name.casefold() for item in imported.groups if item.name}) == 2
    definitions = {item.definition_id: item for item in imported.block_definitions}
    for instance in imported.block_instances:
        line = definitions[instance.definition_id].entities[0]
        assert isinstance(line, LineEntity)
        assert line.end_mm[0] == instance.insertion_mm[0] / 10
    assert len(imported.groups) == 2
    assert all(len(group.members) == 1 for group in imported.groups)
    assert {group.members[0].object_id for group in imported.groups} == {
        instance.instance_id for instance in imported.block_instances
    }
    assert any("块" in warning and "名称" in warning for warning in imported.report.warnings)
    assert any("组" in warning and "名称" in warning for warning in imported.report.warnings)
    repeated = read_sketch_dxf(path)
    assert [item.name for item in repeated.block_definitions] == [
        item.name for item in imported.block_definitions
    ]
    assert [item.name for item in repeated.groups] == [item.name for item in imported.groups]

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    prepared = prepare_dxf_collection_import(imported, app.drawing_collection_snapshot(services))
    loaded.bus.execute(prepared.operation.command_id, prepared.operation.params, "local", version=1)
    assert (
        len(services.kernel.drawing_block_definitions) == len(services.kernel.drawing_groups) == 2
    )
    first = app.drawing_collection_snapshot(services)
    again = prepare_dxf_collection_import(imported, first)
    assert any("块名称冲突" in warning for warning in again.warnings)
    assert any("组名称冲突" in warning for warning in again.warnings)
    loaded.bus.execute(again.operation.command_id, again.operation.params, "local", version=1)
    assert (
        len(services.kernel.drawing_block_definitions) == len(services.kernel.drawing_groups) == 4
    )
    from mycad.core.persistence import save_document

    save = tmp_path / "unicode-collisions.my2d"
    save_document(loaded.document, save)
    reopened = app.open_app_document(services, save)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == first
    reopened.bus.undo_operation()
    assert services.kernel.drawing_block_definitions == services.kernel.drawing_groups == ()


def test_unreferenced_external_blocks_with_casefold_collisions_are_not_merged(
    tmp_path: Path,
) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    for index, name in enumerate(("Straße", "STRASSE"), start=1):
        block = document.blocks.new(name, base_point=(0, 0, 0))
        block.add_line((0, 0), (index, 0))
    path = tmp_path / "unreferenced-casefold.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert not imported.block_instances
    assert len(imported.block_definitions) == 2
    assert len({item.name.casefold() for item in imported.block_definitions}) == 2
    endpoints = [item.entities[0] for item in imported.block_definitions]
    assert all(isinstance(item, LineEntity) for item in endpoints)
    assert {item.end_mm for item in endpoints if isinstance(item, LineEntity)} == {(1, 0), (2, 0)}
    assert any("块名称冲突" in warning for warning in imported.report.warnings)


def test_external_block_member_layer_casefold_collisions_keep_distinct_layers(
    tmp_path: Path,
) -> None:
    from mycad import app
    from mycad.formats.dxf_collection_import import prepare_dxf_collection_import
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    for index, name in enumerate(("Straße", "STRASSE"), start=1):
        document.layers.new(name).dxf.color = index
    for index, layer in enumerate(("Straße", "STRASSE"), start=1):
        block = document.blocks.new(f"B{index}", base_point=(0, 0, 0))
        block.add_line((0, 0), (index, 0), dxfattribs={"layer": layer})
        block.add_text(f"B{index}", dxfattribs={"layer": layer})
        document.modelspace().add_blockref(
            f"B{index}", (index * 10, 0), dxfattribs={"layer": layer}
        )
        document.modelspace().add_line((index, 0), (index, 1), dxfattribs={"layer": layer})
        document.modelspace().add_text(f"T{index}", dxfattribs={"layer": layer})
    path = tmp_path / "layer-casefold.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert len(imported.block_definitions) == 2
    layers = [item.entities[0].layer_name for item in imported.block_definitions]
    assert len({name.casefold() for name in layers}) == 2
    assert all(imported.sketch.layers.get(name).name == name for name in layers)
    assert (
        imported.sketch.layers.get(layers[0]).color_rgb
        != imported.sketch.layers.get(layers[1]).color_rgb
    )
    assert [item.texts[0].layer_name for item in imported.block_definitions] == layers
    assert [item.layer_name for item in imported.block_instances] == layers
    assert [item.layer_name for item in imported.sketch.entities] == layers
    assert [item.layer_name for item in imported.texts] == layers
    assert any("图层" in warning and "名称" in warning for warning in imported.report.warnings)
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    prepared = prepare_dxf_collection_import(imported, app.drawing_collection_snapshot(services))
    loaded.bus.execute(prepared.operation.command_id, prepared.operation.params, "local", version=1)
    snapshot = app.drawing_collection_snapshot(services)
    assert [item.entities[0].layer_name for item in snapshot.block_definitions] == layers
    assert [item.layer_name for item in snapshot.block_instances] == layers
    assert snapshot.layers.get(layers[0]).color_rgb != snapshot.layers.get(layers[1]).color_rgb
    loaded.bus.undo_operation()
    assert not services.kernel.drawing_block_instances


def test_external_text_style_casefold_collisions_preserve_block_and_model_fonts(
    tmp_path: Path,
) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.formats.dxf_collection_import import prepare_dxf_collection_import
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    block = document.blocks.new("Labels", base_point=(0, 0, 0))
    for index, (name, font) in enumerate((("Straße", "first.ttf"), ("STRASSE", "second.ttf"))):
        document.styles.new(name, dxfattribs={"font": font})
        block.add_text(f"B{index}", dxfattribs={"style": name})
        document.modelspace().add_text(f"T{index}", dxfattribs={"style": name})
    document.modelspace().add_blockref("Labels", (0, 0))
    path = tmp_path / "text-style-collision.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert imported.text_styles is not None
    assert len(imported.block_definitions) == 1 and len(imported.texts) == 2
    all_texts = (*imported.block_definitions[0].texts, *imported.texts)
    fonts = {text.text: imported.text_styles.get(text.style_id).font_file for text in all_texts}
    assert fonts == {"B0": "first.ttf", "B1": "second.ttf", "T0": "first.ttf", "T1": "second.ttf"}
    assert any("文字样式" in warning and "名称" in warning for warning in imported.report.warnings)
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    prepared = prepare_dxf_collection_import(imported, app.drawing_collection_snapshot(services))
    loaded.bus.execute(prepared.operation.command_id, prepared.operation.params, "local", version=1)
    snapshot = app.drawing_collection_snapshot(services)
    copied = (*snapshot.block_definitions[0].texts, *snapshot.texts)
    assert {
        text.text: snapshot.text_styles.get(text.style_id).font_file for text in copied
    } == fonts
    save = tmp_path / "text-style-collision.my2d"
    save_document(loaded.document, save)
    reopened = app.open_app_document(services, save)
    assert app.drawing_collection_snapshot(services) == snapshot
    reopened.bus.undo_operation()
    assert not app.drawing_collection_snapshot(services).block_definitions


def test_external_font_name_conflicts_across_separate_blocks_are_reported(tmp_path: Path) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    for index, (name, font) in enumerate((("Straße", "first.ttf"), ("STRASSE", "second.ttf"))):
        document.styles.new(name, dxfattribs={"font": font})
        block = document.blocks.new(f"B{index}", base_point=(0, 0, 0))
        block.add_text(f"T{index}", dxfattribs={"style": name})
        document.modelspace().add_blockref(f"B{index}", (index * 10, 0))
    path = tmp_path / "separate-block-fonts.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert imported.text_styles is not None
    fonts = [
        imported.text_styles.get(block.texts[0].style_id).font_file
        for block in imported.block_definitions
    ]
    assert fonts == ["first.ttf", "second.ttf"]
    assert any("文字样式" in warning and "名称" in warning for warning in imported.report.warnings)


def test_unicode_conflict_sample_roundtrips_through_actual_preview_bytes(tmp_path: Path) -> None:
    import io

    from mycad import app
    from mycad.formats.dxf_collection_import import prepare_dxf_collection_import
    from mycad.formats.dxf_preview import prepare_dxf_output_preview
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    sample = (
        Path(__file__).parents[2]
        / "docs/examples/drawing-collections/external-unicode-conflicts.dxf"
    )
    imported = read_sketch_dxf(sample)
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    prepared = prepare_dxf_collection_import(imported, app.drawing_collection_snapshot(services))
    loaded.bus.execute(prepared.operation.command_id, prepared.operation.params, "local", version=1)
    preview = prepare_dxf_output_preview(services.kernel)
    native = _read(io.StringIO(preview.dxf_bytes.decode("utf-8")))
    assert len(tuple(native.groups)) == 2
    assert sum(item.dxftype() == "INSERT" for item in native.modelspace()) == 2
    path = tmp_path / "unicode-preview.dxf"
    path.write_bytes(preview.dxf_bytes)
    restored = read_sketch_dxf(path)
    assert (
        len(restored.block_definitions)
        == len(restored.block_instances)
        == len(restored.groups)
        == 2
    )
    assert restored.text_styles is not None
    definitions = {item.definition_id: item for item in restored.block_definitions}
    instances = {item.instance_id: item for item in restored.block_instances}
    for index, group in enumerate(restored.groups):
        assert len(group.members) == 1 and group.members[0].kind == "block_instance"
        definition = definitions[instances[group.members[0].object_id].definition_id]
        line = definition.entities[0]
        assert isinstance(line, LineEntity) and line.end_mm == (15 + index * 10, 0)
        assert restored.text_styles.get(definition.texts[0].style_id).font_family == (
            "DejaVu Sans" if index == 0 else "DejaVu Serif"
        )
        assert restored.sketch.layers.get(line.layer_name).color_rgb == (
            (255, 0, 0) if index == 0 else (0, 255, 0)
        )


def test_last_instance_removed_definition_survives_preview_export_and_reimport(
    tmp_path: Path,
) -> None:
    import io

    from mycad import app
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.persistence import save_document
    from mycad.core.sketch_layers import SketchLayer
    from mycad.formats.dxf_preview import prepare_dxf_output_preview
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    layers = services.kernel.drawing_layers.add(SketchLayer("Details", color_rgb=(255, 0, 0)))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    line = LineEntity(uuid4().hex, (0, 0), (8, 0), layer_name="Details")
    text = DrawingText(uuid4().hex, "Definition", (0, 2), layer_name="Details")
    definition = BlockDefinition(uuid4().hex, "Unused", (line,), (text,))
    instance = BlockInstance(uuid4().hex, definition.definition_id, (2, 2))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    loaded.bus.execute(
        "drawing.block_instance.remove", {"instance_id": instance.instance_id}, "local"
    )
    save = tmp_path / "definition-only.my2d"
    save_document(loaded.document, save)
    reopened = app.open_app_document(services, save)
    assert services.kernel.drawing_block_definitions == (definition,)
    assert services.kernel.drawing_block_instances == ()
    preview = prepare_dxf_output_preview(services.kernel)
    native = _read(io.StringIO(preview.dxf_bytes.decode("utf-8")))
    layout = native.blocks.get("Unused")
    assert layout is not None and {item.dxftype() for item in layout} == {"LINE", "TEXT"}
    assert all(item.dxftype() != "INSERT" for item in native.modelspace())
    path = tmp_path / "definition-only.dxf"
    path.write_bytes(preview.dxf_bytes)
    restored = read_sketch_dxf(path)
    assert len(restored.block_definitions) == 1 and not restored.block_instances
    assert restored.block_definitions[0].entities[0].layer_name == "Details"
    assert restored.block_definitions[0].texts[0].text == "Definition"
    reopened.bus.undo_operation()
    assert services.kernel.drawing_block_instances == (instance,)


def test_grouped_block_layer_inheritance_survives_explode_and_dxf_exchange(tmp_path: Path) -> None:
    from dataclasses import replace

    from mycad import app
    from mycad.core.drawing_block_transactions import prepare_block_explode
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance, expand_block
    from mycad.core.drawing_groups import DrawingGroup
    from mycad.core.persistence import save_document
    from mycad.core.sketch_layers import SketchLayer
    from mycad.formats.dxf_preview import prepare_dxf_output_preview
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    layers = services.kernel.drawing_layers.add(SketchLayer("Insert")).add(SketchLayer("Detail"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    lines = (
        LineEntity(uuid4().hex, (0, 0), (4, 0)),
        LineEntity(uuid4().hex, (0, 2), (4, 2), layer_name="Detail"),
    )
    texts = (
        DrawingText(uuid4().hex, "Zero", (0, 3)),
        DrawingText(uuid4().hex, "Detail", (0, 5), layer_name="Detail"),
    )
    definition = BlockDefinition(uuid4().hex, "Layered", lines, texts)
    instance = BlockInstance(uuid4().hex, definition.definition_id, (10, 20), 90, 2, "Insert")
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("block_instance", instance.instance_id),),
        name="LayeredGroup",
    )
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    before = app.drawing_collection_snapshot(services)
    preview = prepare_dxf_output_preview(services.kernel)
    path = tmp_path / "block-before-explode.dxf"
    path.write_bytes(preview.dxf_bytes)
    imported = read_sketch_dxf(path)
    assert imported.text_styles is not None
    expansion = expand_block(
        imported.block_definitions[0], imported.block_instances[0], imported.text_styles
    )
    assert [item.layer_name for item in expansion.entities] == ["Insert", "Detail"]
    assert [item.layer_name for item in expansion.texts] == ["Insert", "Detail"]
    assert imported.groups[0].members[0].kind == "block_instance"

    operation = prepare_block_explode(before, instance.instance_id)
    loaded.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    exploded = app.drawing_collection_snapshot(services)
    expected = expand_block(definition, instance, before.text_styles)
    assert (
        tuple(
            replace(actual, entity_id=source.entity_id)
            for actual, source in zip(
                exploded.sketches[-1].entities, expected.entities, strict=True
            )
        )
        == expected.entities
    )
    assert (
        tuple(
            replace(actual, text_id=source.text_id)
            for actual, source in zip(exploded.texts, expected.texts, strict=True)
        )
        == expected.texts
    )
    assert [item.layer_name for item in exploded.sketches[-1].entities] == ["Insert", "Detail"]
    assert [item.layer_name for item in exploded.texts] == ["Insert", "Detail"]
    assert {item.kind for item in exploded.groups[0].members} == {"geometry", "text"}
    preview = prepare_dxf_output_preview(services.kernel)
    path = tmp_path / "block-after-explode.dxf"
    path.write_bytes(preview.dxf_bytes)
    imported_exploded = read_sketch_dxf(path)
    assert [item.layer_name for item in imported_exploded.sketch.entities] == ["Insert", "Detail"]
    assert [item.layer_name for item in imported_exploded.texts] == ["Insert", "Detail"]
    assert len(imported_exploded.groups[0].members) == 4
    save = tmp_path / "exploded-layers.my2d"
    save_document(loaded.document, save)
    reopened = app.open_app_document(services, save)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before


def test_exploded_overlapping_groups_keep_direct_selection_and_dxf_mapping(tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.drawing_block_transactions import prepare_block_explode
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.drawing_groups import DrawingGroup, expand_group_selection
    from mycad.core.persistence import save_document
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (4, 0))
    text = DrawingText(uuid4().hex, "InBlock", (0, 2))
    marker = DrawingText(uuid4().hex, "Marker", (30, 0))
    anchor = DrawingText(uuid4().hex, "FirstOnly", (40, 0))
    definition = BlockDefinition(uuid4().hex, "Overlap", (line,), (text,))
    instance = BlockInstance(uuid4().hex, definition.definition_id, (10, 20), 90, 2)
    instance_ref = DrawingObjectRef("block_instance", instance.instance_id)
    marker_ref = DrawingObjectRef("text", marker.text_id)
    anchor_ref = DrawingObjectRef("text", anchor.text_id)
    first = DrawingGroup(uuid4().hex, (anchor_ref, instance_ref), name="First")
    second = DrawingGroup(uuid4().hex, (instance_ref, marker_ref), name="Second")
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    loaded.bus.execute("drawing.text.add", marker.to_mapping(), "local")
    loaded.bus.execute("drawing.text.add", anchor.to_mapping(), "local")
    loaded.bus.execute("drawing.group.create", first.to_mapping(), "local")
    loaded.bus.execute("drawing.group.create", second.to_mapping(), "local")
    before = app.drawing_collection_snapshot(services)
    operation = prepare_block_explode(before, instance.instance_id)
    loaded.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    after = app.drawing_collection_snapshot(services)
    first_after, second_after = after.groups
    assert first_after.members[0] == anchor_ref
    assert first_after.members[1:] == second_after.members[:-1]
    assert second_after.members[-1] == marker_ref
    assert expand_group_selection((marker_ref,), after.groups) == frozenset(second_after.members)
    assert anchor_ref not in expand_group_selection((marker_ref,), after.groups)
    path = tmp_path / "exploded-overlap.dxf"
    write_sketches_dxf(
        after.sketches,
        path,
        texts=after.texts,
        text_styles=after.text_styles,
        drawing_layers=after.layers,
        groups=after.groups,
        block_definitions=after.block_definitions,
    )
    imported = read_sketch_dxf(path)
    by_name = {group.name: group for group in imported.groups}
    assert len(by_name["First"].members) == len(by_name["Second"].members) == 3
    assert len(set(by_name["First"].members) & set(by_name["Second"].members)) == 2
    imported_marker = next(item for item in imported.texts if item.text == "Marker")
    imported_anchor = next(item for item in imported.texts if item.text == "FirstOnly")
    marker_selection = expand_group_selection(
        (DrawingObjectRef("text", imported_marker.text_id),), imported.groups
    )
    assert marker_selection == frozenset(by_name["Second"].members)
    assert DrawingObjectRef("text", imported_anchor.text_id) not in marker_selection
    saved = tmp_path / "exploded-overlap.my2d"
    save_document(loaded.document, saved)
    reopened = app.open_app_document(services, saved)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == after


def test_deleted_overlap_member_cleans_empty_group_before_dxf_export(tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.drawing_groups import DrawingGroup
    from mycad.core.persistence import save_document
    from mycad.formats.dxf_preview import prepare_dxf_output_preview
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    removed = DrawingText(uuid4().hex, "Removed", (1, 2))
    kept = DrawingText(uuid4().hex, "Kept", (4, 2))
    removed_ref = DrawingObjectRef("text", removed.text_id)
    kept_ref = DrawingObjectRef("text", kept.text_id)
    first = DrawingGroup(uuid4().hex, (removed_ref,), name="EmptyAfterDelete", selectable=False)
    second = DrawingGroup(uuid4().hex, (removed_ref, kept_ref), name="Surviving", selectable=False)
    for text in (removed, kept):
        loaded.bus.execute("drawing.text.add", text.to_mapping(), "local")
    for group in (first, second):
        loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    before = app.drawing_collection_snapshot(services)
    loaded.bus.execute("drawing.text.remove", {"text_id": removed.text_id}, "local")
    after = app.drawing_collection_snapshot(services)
    assert after.groups == (replace(second, members=(kept_ref,)),)
    assert after.texts == (kept,)
    preview = prepare_dxf_output_preview(services.kernel)
    path = tmp_path / "overlap-delete.dxf"
    path.write_bytes(preview.dxf_bytes)
    imported = read_sketch_dxf(path)
    assert len(imported.groups) == len(imported.texts) == 1
    assert imported.groups[0].name == "Surviving" and not imported.groups[0].selectable
    assert imported.texts[0].text == "Kept"
    assert imported.groups[0].members == (DrawingObjectRef("text", imported.texts[0].text_id),)
    saved = tmp_path / "overlap-delete.my2d"
    save_document(loaded.document, saved)
    reopened = app.open_app_document(services, saved)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == after


def test_native_annotation_layers_follow_casefold_collision_mapping(tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.drawing_groups import DrawingGroup
    from mycad.core.geometric_tolerance import DatumIdentifier, FeatureControlFrame, ToleranceRow
    from mycad.formats.dxf_collection_import import prepare_dxf_collection_import
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("position", 0.1, 2),), (10, 10))
    datum = DatumIdentifier(uuid4().hex, "A", (20, 10), (16, 0), layout_mode="shared")
    dimension = DetachedDimension(uuid4().hex, "rotated", (0, 0), (10, 0), (0, 5), 0, 10)
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("tolerance", frame.frame_id),
            DrawingObjectRef("datum", datum.datum_id),
            DrawingObjectRef("reference_dimension", dimension.dimension_id),
        ),
        name="Annotations",
    )
    path = tmp_path / "annotation-layer-collision.dxf"
    write_sketches_dxf(
        (),
        path,
        tolerance_frames=(frame,),
        datum_identifiers=(datum,),
        reference_dimensions=(dimension,),
        groups=(group,),
    )
    document = _readfile(path)
    for name in ("Straße", "STRASSE"):
        document.layers.new(name)
    for item in document.modelspace():
        if item.dxftype() == "TOLERANCE":
            item.dxf.layer = "Straße"
        elif item.dxftype() in ("INSERT", "DIMENSION"):
            item.dxf.layer = "STRASSE"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert len(imported.tolerance_frames) == len(imported.datum_identifiers) == 1
    assert len(imported.detached_dimensions) == 1
    source_layer = imported.tolerance_frames[0].layer_name
    datum_layer = imported.datum_identifiers[0].layer_name
    dimension_layer = imported.detached_dimensions[0].layer_name
    assert source_layer.casefold() != datum_layer.casefold()
    assert datum_layer == dimension_layer
    assert imported.sketch.layers.get(datum_layer).name == datum_layer
    assert {member.kind for member in imported.groups[0].members} == {
        "tolerance",
        "datum",
        "reference_dimension",
    }
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    prepared = prepare_dxf_collection_import(imported, app.drawing_collection_snapshot(services))
    loaded.bus.execute(prepared.operation.command_id, prepared.operation.params, "local", version=1)
    snapshot = app.drawing_collection_snapshot(services)
    assert snapshot.frames[0].layer_name == source_layer
    assert (
        snapshot.datums[0].layer_name == snapshot.reference_dimensions[0].layer_name == datum_layer
    )
    assert len(snapshot.groups) == 1
    loaded.bus.undo_operation()
    assert not app.drawing_collection_snapshot(services).groups


def test_external_block_import_converts_units_and_base_point(tmp_path: Path) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=1)
    layout = document.blocks.new("Inches", base_point=(1, 1, 0))
    layout.add_line((1, 1), (2, 1))
    document.modelspace().add_blockref("Inches", (3, 4), dxfattribs={"xscale": 2, "yscale": 2})
    path = tmp_path / "inch-block.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    line = result.block_definitions[0].entities[0]
    assert isinstance(line, LineEntity)
    assert line.start_mm == pytest.approx((0, 0)) and line.end_mm == pytest.approx((25.4, 0))
    assert result.block_instances[0].insertion_mm == pytest.approx((76.2, 101.6))
    assert result.block_instances[0].scale == 2


def test_group_roundtrip_restores_associated_and_detached_dimension_members(tmp_path: Path) -> None:
    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.drawing_groups import DrawingGroup
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    reference = DetachedDimension(uuid4().hex, "rotated", (0, 0), (10, 0), (0, 5), 0, 10)
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),
            DrawingObjectRef("dimension", dimension.constraint_id, sketch.sketch_id),
            DrawingObjectRef("reference_dimension", reference.dimension_id),
        ),
        name="Dimensions",
    )
    path = tmp_path / "dimension-group.dxf"
    report = write_sketches_dxf((sketch,), path, reference_dimensions=(reference,), groups=(group,))
    document = _readfile(path)
    native = document.groups.get("Dimensions")
    assert native is not None and sorted(item.dxftype() for item in native) == [
        "DIMENSION",
        "DIMENSION",
        "LINE",
    ]
    assert not any("成员不完整" in item for item in report.warnings)
    result = read_sketch_dxf(path)
    assert (
        len(result.sketch.constraints) == len(result.detached_dimensions) == len(result.groups) == 1
    )
    assert set(result.groups[0].members) == {
        DrawingObjectRef("geometry", result.sketch.entities[0].entity_id, result.sketch.sketch_id),
        DrawingObjectRef(
            "dimension", result.sketch.constraints[0].constraint_id, result.sketch.sketch_id
        ),
        DrawingObjectRef("reference_dimension", result.detached_dimensions[0].dimension_id),
    }


def test_associated_dimension_uses_modified_native_layer_with_casefold_collision(
    tmp_path: Path,
) -> None:
    from mycad.core.drawing_groups import DrawingGroup
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("dimension", dimension.constraint_id, sketch.sketch_id),),
        name="DimensionGroup",
    )
    path = tmp_path / "associated-dimension-layer.dxf"
    write_sketches_dxf((sketch,), path, groups=(group,))
    document = _readfile(path)
    for name in ("Straße", "STRASSE"):
        document.layers.new(name)
    for item in document.modelspace():
        if item.dxftype() == "LINE":
            item.dxf.layer = "Straße"
        elif item.dxftype() == "DIMENSION":
            item.dxf.layer = "STRASSE"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert len(result.sketch.constraints) == len(result.groups) == 1
    line_layer = result.sketch.entities[0].layer_name
    dimension_layer = result.sketch.constraints[0].layer_name
    assert dimension_layer is not None
    assert line_layer.casefold() != dimension_layer.casefold()
    assert result.sketch.layers.get(dimension_layer).name == dimension_layer
    assert result.groups[0].members[0].kind == "dimension"


@pytest.mark.parametrize("explicit", [False, True])
def test_associated_dimension_preserves_implicit_or_explicit_layer(
    tmp_path: Path, explicit: bool
) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    layers = SketchLayerTable().add(SketchLayer("Dimensions"))
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        layer_name="Dimensions" if explicit else None,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,), layers=layers)
    path = tmp_path / "dimension-layer.dxf"
    write_sketches_dxf((sketch,), path)
    imported = read_sketch_dxf(path)
    assert imported.sketch.constraints[0].layer_name == ("Dimensions" if explicit else None)


def test_group_does_not_restore_dimension_with_broken_native_reference(tmp_path: Path) -> None:
    from mycad.core.drawing_groups import DrawingGroup
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),
            DrawingObjectRef("dimension", dimension.constraint_id, sketch.sketch_id),
        ),
        name="Damaged",
    )
    path = tmp_path / "broken-reference.dxf"
    write_sketches_dxf((sketch,), path, groups=(group,))
    document = _readfile(path)
    native_line = next(item for item in document.modelspace() if item.dxftype() == "LINE")
    native_line.discard_xdata("MYCAD")
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert imported.sketch.constraints == ()
    assert len(imported.groups) == 1 and len(imported.groups[0].members) == 1
    assert imported.groups[0].members[0].kind == "geometry"
    assert any("Damaged" in warning and "无法" in warning for warning in imported.report.warnings)


def test_group_roundtrip_restores_frame_with_leader_and_datum(tmp_path: Path) -> None:
    from mycad.core.drawing_groups import DrawingGroup
    from mycad.core.geometric_tolerance import DatumIdentifier, FeatureControlFrame, ToleranceRow
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

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
    path = tmp_path / "annotations-group.dxf"
    report = write_sketches_dxf(
        (), path, tolerance_frames=(frame,), datum_identifiers=(datum,), groups=(group,)
    )
    document = _readfile(path)
    native = document.groups.get("Annotations")
    assert native is not None and sorted(item.dxftype() for item in native) == [
        "INSERT",
        "LEADER",
        "TOLERANCE",
    ]
    assert not any("成员不完整" in item for item in report.warnings)
    result = read_sketch_dxf(path)
    assert result.tolerance_frames == (frame,) and result.datum_identifiers == (datum,)
    assert len(result.groups) == 1
    assert set(result.groups[0].members) == {
        DrawingObjectRef("tolerance", frame.frame_id),
        DrawingObjectRef("datum", datum.datum_id),
    }


def test_group_does_not_recover_frame_without_all_leader_handles(tmp_path: Path) -> None:
    from mycad.core.drawing_groups import DrawingGroup
    from mycad.core.geometric_tolerance import FeatureControlFrame, ToleranceRow
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (10, 10),
        leader_target_mm=(0, 0),
        leader_offsets=((-5, -5),),
        leader_anchor_offset=(0, -3),
    )
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),
            DrawingObjectRef("tolerance", frame.frame_id),
        ),
        name="PartialFrame",
    )
    path = tmp_path / "missing-leader.dxf"
    write_sketches_dxf((sketch,), path, tolerance_frames=(frame,), groups=(group,))
    document = _readfile(path)
    native_group = document.groups.get("PartialFrame")
    assert native_group is not None
    native_group.set_data(tuple(item for item in native_group if item.dxftype() != "LEADER"))
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert result.tolerance_frames == (frame,)
    assert len(result.groups) == 1 and len(result.groups[0].members) == 1
    assert result.groups[0].members[0].kind == "geometry"
    assert any(
        "PartialFrame" in warning and "无法" in warning for warning in result.report.warnings
    )


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_group_roundtrip_includes_complete_surface_indication(tmp_path: Path, owner: str) -> None:
    from mycad.core.drawing_groups import DrawingGroup
    from mycad.core.geometric_tolerance import (
        DatumAttachment,
        DatumIdentifier,
        FeatureControlFrame,
        SurfaceIndication,
        ToleranceRow,
    )
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    surface = SurfaceIndication((5, 8), (10, 8), 0.5, ((0, 3),), auto_normal=True)
    datum = DatumIdentifier(
        uuid4().hex, "A", (30, 30), (10, 0), attachment=attachment, surface_indication=surface
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (30, 30),
        leader_target_mm=(10, 0),
        leader_anchor_offset=(0, -2),
        leader_attachment=attachment,
        surface_indication=surface,
    )
    ref = (
        DrawingObjectRef("datum", datum.datum_id)
        if owner == "datum"
        else DrawingObjectRef("tolerance", frame.frame_id)
    )
    group = DrawingGroup(uuid4().hex, (ref,), name="Surface")
    path = tmp_path / f"surface-{owner}.dxf"
    write_sketches_dxf(
        (sketch,),
        path,
        datum_identifiers=(datum,) if owner == "datum" else (),
        tolerance_frames=(frame,) if owner == "frame" else (),
        groups=(group,),
    )
    result = read_sketch_dxf(path)
    assert len(result.groups) == 1 and result.groups[0].members == (ref,)
    restored = result.datum_identifiers[0] if owner == "datum" else result.tolerance_frames[0]
    assert restored.surface_indication == surface
    assert not any("Surface" in warning and "无法" in warning for warning in result.report.warnings)


def test_graphics_export_reports_group_loss_from_frame_conversion() -> None:
    from mycad import app
    from mycad.core.drawing_groups import DrawingGroup
    from mycad.core.geometric_tolerance import FeatureControlFrame, ToleranceRow
    from mycad.formats.dxf_preview import prepare_dxf_output_preview

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("position", 0.1, 2),), (10, 10))
    loaded.bus.execute(
        "drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local", version=28
    )
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("tolerance", frame.frame_id),), name="FrameGroup"
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    preview = prepare_dxf_output_preview(services.kernel, tolerance_graphics=True)
    assert any("FrameGroup" in warning and "组" in warning for warning in preview.report.warnings)


def test_real_mixed_group_with_image_survives_native_and_reports_dxf_loss(tmp_path: Path) -> None:
    import base64
    import struct
    import zlib

    from mycad import app
    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.drawing_groups import DrawingGroup
    from mycad.core.drawing_raster import DrawingRaster
    from mycad.core.drawing_transactions import prepare_collection_translation
    from mycad.core.geometric_tolerance import DatumIdentifier, FeatureControlFrame, ToleranceRow
    from mycad.core.persistence import save_document
    from mycad.formats.dxf_preview import prepare_dxf_output_preview
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00\xff"))
        + chunk(b"IEND", b"")
    )
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    raster = DrawingRaster(uuid4().hex, base64.b64encode(png).decode("ascii"), (3, 3), 5, 5)
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("position", 0.1, 2),), (10, 10))
    datum = DatumIdentifier(uuid4().hex, "A", (20, 10), (16, 0), layout_mode="shared")
    dimension = DetachedDimension(uuid4().hex, "rotated", (0, 0), (10, 0), (0, 5), 0, 10)
    loaded.bus.execute("drawing.raster.add", raster.to_mapping(), "local", version=1)
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
        "local",
    )
    loaded.bus.execute(
        "drawing.reference_dimensions.batch", {"add": [dimension.to_mapping()]}, "local"
    )
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),
            DrawingObjectRef("raster", raster.image_id),
            DrawingObjectRef("tolerance", frame.frame_id),
            DrawingObjectRef("datum", datum.datum_id),
            DrawingObjectRef("reference_dimension", dimension.dimension_id),
        ),
        name="MixedImageAnnotations",
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    image_only = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("raster", raster.image_id),), name="ImageOnly"
    )
    loaded.bus.execute("drawing.group.create", image_only.to_mapping(), "local")
    path = tmp_path / "mixed.my2d"
    save_document(loaded.document, path)
    loaded_after_reopen = app.open_app_document(services, path)
    assert services.kernel.drawing_rasters == (raster,)
    assert services.kernel.drawing_groups == (group, image_only)
    before = app.drawing_collection_snapshot(services)
    move = prepare_collection_translation(before, (group.members[0],), sketch.frame, (0, 3))
    loaded_after_reopen.bus.execute(move.command_id, move.params, "local", version=move.version)
    moved = app.drawing_collection_snapshot(services)
    assert moved.sketches[0].entities[0] == LineEntity(line.entity_id, (0, 3), (10, 3))
    assert moved.rasters[0].origin_mm == (3, 6)
    assert moved.frames[0].position_mm == (10, 13)
    assert moved.datums[0].position_mm == (20, 13)
    assert moved.reference_dimensions[0].first_mm == (0, 3)
    loaded_after_reopen.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    preview = prepare_dxf_output_preview(services.kernel)
    assert any("图片未导出" in message for message in preview.report.warnings)
    assert any(
        "MixedImageAnnotations" in message and "不完整" in message
        for message in preview.report.warnings
    )
    assert any("ImageOnly" in message and "组" in message for message in preview.report.warnings)
    exported = tmp_path / "mixed.dxf"
    exported.write_bytes(preview.dxf_bytes)
    assert _readfile(exported).groups.get("ImageOnly") is None
    restored = read_sketch_dxf(exported)
    assert len(restored.groups) == 1
    assert {item.kind for item in restored.groups[0].members} == {
        "geometry",
        "tolerance",
        "datum",
        "reference_dimension",
    }


def test_graphics_export_keeps_frame_proxy_entities_in_native_group() -> None:
    import io

    from mycad import app
    from mycad.core.drawing_groups import DrawingGroup
    from mycad.core.geometric_tolerance import FeatureControlFrame, ToleranceRow
    from mycad.formats.dxf_preview import prepare_dxf_output_preview

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("position", 0.1, 2),), (10, 10))
    loaded.bus.execute(
        "drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local", version=28
    )
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("tolerance", frame.frame_id),), name="FrameGroup"
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    overlap = DrawingGroup(uuid4().hex, group.members, name="Overlapping")
    loaded.bus.execute("drawing.group.create", overlap.to_mapping(), "local")
    preview = prepare_dxf_output_preview(services.kernel, tolerance_graphics=True)
    document = _read(io.StringIO(preview.dxf_bytes.decode("utf-8")))
    native_group = document.groups.get("FrameGroup")
    assert native_group is not None
    members = tuple(native_group)
    assert members and all(entity.dxftype() != "TOLERANCE" for entity in members)
    assert {entity.dxf.handle for entity in members} == {
        entity.dxf.handle for entity in document.modelspace()
    }
    second = document.groups.get("Overlapping")
    assert second is not None
    assert {entity.dxf.handle for entity in second} == {entity.dxf.handle for entity in members}


def test_group_does_not_recover_frame_when_leader_is_inconsistent(tmp_path: Path) -> None:
    from mycad.core.drawing_groups import DrawingGroup
    from mycad.core.geometric_tolerance import FeatureControlFrame, ToleranceRow
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (10, 10),
        leader_target_mm=(0, 0),
        leader_offsets=((-5, -5),),
        leader_anchor_offset=(0, -3),
    )
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),
            DrawingObjectRef("tolerance", frame.frame_id),
        ),
        name="AlteredLeader",
    )
    path = tmp_path / "altered-leader.dxf"
    write_sketches_dxf((sketch,), path, tolerance_frames=(frame,), groups=(group,))
    document = _readfile(path)
    leader = next(item for item in document.modelspace() if item.dxftype() == "LEADER")
    leader.dxf.has_arrowhead = 0
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert len(result.groups) == 1 and len(result.groups[0].members) == 1
    assert result.groups[0].members[0].kind == "geometry"
    assert any(
        "AlteredLeader" in warning and "无法" in warning for warning in result.report.warnings
    )


def test_unreferenced_nested_block_is_rejected_without_importing_internal_dependency(
    tmp_path: Path,
) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    inner = document.blocks.new("Internal", base_point=(0, 0, 0))
    inner.add_line((0, 0), (1, 0))
    outer = document.blocks.new("NestedOuter", base_point=(0, 0, 0))
    outer.add_line((0, 0), (2, 0))
    outer.add_blockref("Internal", (0, 0))
    standalone = document.blocks.new("Standalone", base_point=(0, 0, 0))
    standalone.add_line((0, 0), (3, 0))
    path = tmp_path / "nested-definitions.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert [item.name for item in result.block_definitions] == ["Standalone"]
    assert result.block_instances == ()
    assert any("NestedOuter" in item and "未导入" in item for item in result.report.warnings)


@pytest.mark.parametrize("inserted", [False, True])
def test_dynamic_block_extension_dictionary_is_rejected(tmp_path: Path, inserted: bool) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    layout = document.blocks.new("Dynamic", base_point=(0, 0, 0))
    layout.add_line((0, 0), (2, 0))
    layout.block_record.new_extension_dict().add_dictionary("ACAD_ENHANCEDBLOCK")
    if inserted:
        document.modelspace().add_blockref("Dynamic", (0, 0))
    path = tmp_path / f"dynamic-{inserted}.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert imported.block_definitions == imported.block_instances == ()
    assert any("Dynamic" in item and "动态" in item for item in imported.report.warnings)


def test_unrelated_block_extension_dictionary_does_not_hide_definition(tmp_path: Path) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    layout = document.blocks.new("Normal", base_point=(0, 0, 0))
    layout.add_line((0, 0), (2, 0))
    layout.block_record.new_extension_dict().add_dictionary("THIRD_PARTY_DATA")
    path = tmp_path / "normal-extension.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert len(imported.block_definitions) == 1 and imported.block_definitions[0].name == "Normal"


@pytest.mark.parametrize("case", ["overflow", "tiny_nonuniform"])
def test_external_block_rejects_unrenderable_or_nonuniform_instance_without_losing_others(
    tmp_path: Path, case: str
) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    block = document.blocks.new("Limits", base_point=(0, 0, 0))
    block.add_line((0, 0), (2, 0))
    good = document.modelspace().add_blockref("Limits", (0, 0))
    scales = (
        {"xscale": 1e308, "yscale": 1e308, "zscale": 1e308}
        if case == "overflow"
        else {"xscale": 1e-11, "yscale": 1.05e-11, "zscale": 1}
    )
    bad = document.modelspace().add_blockref("Limits", (4, 5), dxfattribs=scales)
    document.groups.new("Instances").set_data((good, bad))
    path = tmp_path / f"block-limits-{case}.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert len(result.block_definitions) == len(result.block_instances) == 1
    assert result.block_instances[0].insertion_mm == (0, 0)
    assert len(result.groups) == 1 and len(result.groups[0].members) == 1
    assert any("块实例" in warning and "未导入" in warning for warning in result.report.warnings)
    if case == "tiny_nonuniform":
        assert any("正等比" in warning for warning in result.report.warnings)


def test_export_preserves_tiny_scale_and_group_on_roundtrip(tmp_path: Path) -> None:
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.drawing_groups import DrawingGroup
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    line = LineEntity(uuid4().hex, (0, 0), (1e15, 0))
    definition = BlockDefinition(uuid4().hex, "Scale", (line,), ())
    tiny = BlockInstance(uuid4().hex, definition.definition_id, (0, 0), scale=1e-13)
    normal = BlockInstance(uuid4().hex, definition.definition_id, (10, 0))
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("block_instance", tiny.instance_id),
            DrawingObjectRef("block_instance", normal.instance_id),
        ),
        name="MixedScale",
    )
    path = tmp_path / "tiny-scale.dxf"
    report = write_sketches_dxf(
        (), path, block_definitions=(definition,), block_instances=(tiny, normal), groups=(group,)
    )
    document = _readfile(path)
    inserts = tuple(item for item in document.modelspace() if item.dxftype() == "INSERT")
    assert len(inserts) == 2
    tiny_native = next(item for item in inserts if item.dxf.insert == (0, 0, 0))
    assert tiny_native.dxf.xscale == 1e-13
    group_out = document.groups.get("MixedScale")
    assert group_out is not None and len(tuple(group_out)) == 2
    assert report.entity_count == 2 and not report.warnings
    imported = read_sketch_dxf(path)
    assert sorted(item.scale for item in imported.block_instances) == [1e-13, 1]
    assert len(imported.groups[0].members) == 2


def test_dxf_preview_preserves_tiny_scale_in_actual_bytes() -> None:
    import io
    import xml.etree.ElementTree as ET

    from mycad import app
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.formats.dxf_preview import prepare_dxf_output_preview

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    definition = BlockDefinition(
        uuid4().hex, "Scale", (LineEntity(uuid4().hex, (0, 0), (1e15, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0), scale=1e-13)
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    preview = prepare_dxf_output_preview(services.kernel)
    native = _read(io.StringIO(preview.dxf_bytes.decode("utf-8")))
    inserts = tuple(item for item in native.modelspace() if item.dxftype() == "INSERT")
    assert len(inserts) == 1 and inserts[0].dxf.xscale == 1e-13
    assert preview.report.entity_count == 1 and not preview.report.warnings
    assert ET.fromstring(preview.svg_bytes).find(".//{http://www.w3.org/2000/svg}path") is not None


@pytest.mark.parametrize("case", ["tiny_uniform", "tiny_nonuniform", "zero"])
@pytest.mark.parametrize("file_format", ["ascii", "binary"])
def test_external_insert_uses_original_scale_before_library_normalization(
    tmp_path: Path, case: str, file_format: str
) -> None:
    import struct

    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    block = document.blocks.new("RawScale", base_point=(0, 0, 0))
    block.add_line((0, 0), (1e15, 0))
    good = document.modelspace().add_blockref("RawScale", (0, 0))
    raw = document.modelspace().add_blockref(
        "RawScale", (4, 5), dxfattribs={"xscale": 1e-10, "yscale": 1e-10}
    )
    document.groups.new("RawGroup").set_data((good, raw))
    path = tmp_path / f"raw-scale-{case}.dxf"
    xscale = 0.0 if case == "zero" else 1e-13
    yscale = 2e-13 if case == "tiny_nonuniform" else xscale
    if file_format == "binary":
        cast("Callable[..., None]", document.saveas)(path, fmt="bin")
        content_bytes = path.read_bytes()
        for code, value in ((41, xscale), (42, yscale)):
            original = struct.pack("<Hd", code, 1e-10)
            assert content_bytes.count(original) == 1
            content_bytes = content_bytes.replace(original, struct.pack("<Hd", code, value))
        path.write_bytes(content_bytes)
    else:
        document.saveas(path)
        content = path.read_text(encoding="utf-8")
        start = content.index(f"\n  5\n{raw.dxf.handle}\n")
        end = content.index("\n  0\n", start)
        entity = content[start:end]
        entity = entity.replace("\n 41\n1e-10\n", f"\n 41\n{xscale}\n")
        entity = entity.replace("\n 42\n1e-10", f"\n 42\n{yscale}")
        path.write_text(content[:start] + entity + content[end:], encoding="utf-8")
    result = read_sketch_dxf(path)
    if case == "tiny_uniform":
        assert len(result.block_instances) == 2
        imported = next(item for item in result.block_instances if item.insertion_mm == (4, 5))
        assert imported.scale == 1e-13
        assert len(result.groups[0].members) == 2
    else:
        assert len(result.block_instances) == 1
        assert result.block_instances[0].insertion_mm == (0, 0)
        assert len(result.groups[0].members) == 1
        assert any("正等比" in warning for warning in result.report.warnings)


def test_far_offset_rectangle_block_and_exploded_group_export_preview(tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.drawing_block_transactions import prepare_block_explode
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance, expand_block
    from mycad.core.drawing_groups import DrawingGroup
    from mycad.core.drawing_text import TextStyleTable
    from mycad.core.sketch import PolylineEntity, RectangleEntity
    from mycad.formats.dxf_preview import prepare_dxf_output_preview
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    rectangle = RectangleEntity(uuid4().hex, (1e9, 1e9), (1e9 + 1, 1e9 + 2))
    definition = BlockDefinition(uuid4().hex, "Far", (rectangle,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 7), 30)
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    group = DrawingGroup(uuid4().hex, (DrawingObjectRef("block_instance", instance.instance_id),))
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    original = app.drawing_collection_snapshot(services)
    source = expand_block(definition, instance, original.text_styles).entities[0]
    assert isinstance(source, PolylineEntity)
    preview = prepare_dxf_output_preview(services.kernel)
    block_path = tmp_path / "far-block.dxf"
    block_path.write_bytes(preview.dxf_bytes)
    restored = read_sketch_dxf(block_path)
    assert (
        len(restored.block_definitions)
        == len(restored.block_instances)
        == len(restored.groups)
        == 1
    )
    restored_instance = restored.block_instances[0]
    assert restored.groups[0].members == (
        DrawingObjectRef("block_instance", restored_instance.instance_id),
    )
    expanded = expand_block(
        restored.block_definitions[0], restored_instance, restored.text_styles or TextStyleTable()
    ).entities[0]
    assert isinstance(expanded, PolylineEntity)
    for actual, expected in zip(expanded.points_mm, source.points_mm, strict=True):
        assert actual == pytest.approx(expected, abs=1e-6)
    operation = prepare_block_explode(original, instance.instance_id)
    loaded.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    preview = prepare_dxf_output_preview(services.kernel)
    exploded_path = tmp_path / "far-exploded.dxf"
    exploded_path.write_bytes(preview.dxf_bytes)
    exploded = read_sketch_dxf(exploded_path)
    assert exploded.sketch is not None and len(exploded.groups) == 1
    entity = exploded.sketch.entities[0]
    assert isinstance(entity, PolylineEntity)
    assert exploded.groups[0].members[0].object_id == entity.entity_id
    for actual, expected in zip(entity.points_mm, source.points_mm, strict=True):
        assert actual == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize("yscale", [1.00000000005, 0.99999999995])
def test_external_nearly_uniform_block_scale_is_not_silently_changed(
    tmp_path: Path, yscale: float
) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    block = document.blocks.new("Long", base_point=(0, 0, 0))
    block.add_line((0, 0), (0, 1e12))
    good = document.modelspace().add_blockref("Long", (0, 0))
    bad = document.modelspace().add_blockref(
        "Long", (20, 0), dxfattribs={"xscale": 1, "yscale": yscale}
    )
    document.groups.new("Mixed").set_data((good, bad))
    path = tmp_path / "nearly-uniform.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert len(imported.block_instances) == 1
    assert imported.block_instances[0].insertion_mm == (0, 0)
    assert len(imported.groups) == 1 and len(imported.groups[0].members) == 1
    assert any("正等比" in warning for warning in imported.report.warnings)
    assert any("组 Mixed" in warning and "无法" in warning for warning in imported.report.warnings)


@pytest.mark.parametrize("tilted", ["instance", "circle", "mtext"])
def test_external_block_with_small_out_of_plane_normal_is_not_flattened(
    tmp_path: Path, tilted: str
) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    document.blocks.new("Good", base_point=(0, 0, 0)).add_line((0, 0), (1e12, 0))
    block = document.blocks.new("Tilted", base_point=(0, 0, 0))
    block.add_line((0, 0), (1e12, 0))
    if tilted == "circle":
        block.add_circle((0, 0), 1e12, dxfattribs={"extrusion": (5e-10, 0, 1)})
    elif tilted == "mtext":
        block.add_mtext("Text", dxfattribs={"extrusion": (5e-10, 0, 1), "char_height": 2})
    good = document.modelspace().add_blockref("Good", (0, 0))
    attributes = {"extrusion": (5e-10, 0, 1)} if tilted == "instance" else {}
    bad = document.modelspace().add_blockref("Tilted", (10, 0), dxfattribs=attributes)
    document.groups.new("Mixed").set_data((good, bad))
    path = tmp_path / f"tilted-{tilted}.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert len(imported.block_instances) == 1
    assert imported.block_instances[0].insertion_mm == (0, 0)
    assert len(imported.groups) == 1 and len(imported.groups[0].members) == 1
    assert any("Tilted" in warning and "未导入" in warning for warning in imported.report.warnings)
    assert any("组 Mixed" in warning and "无法" in warning for warning in imported.report.warnings)


@pytest.mark.parametrize("difference", ["weight", "knot"])
def test_external_block_rejects_subtle_unrepresentable_spline(
    tmp_path: Path, difference: str
) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    block = document.blocks.new("SubtleSpline", base_point=(0, 0, 0))
    spline = block.add_spline()
    spline.set_open_uniform([(0, 0), (1e12, 1e12), (2e12, 1e12), (3e12, 1e12), (4e12, 0)])
    if difference == "weight":
        spline.weights = [1, 1, 1.0000000000005, 1, 1]
    else:
        spline.knots = [0, 0, 0, 0, 0.5000000001, 1, 1, 1, 1]
    good = document.blocks.new("Good", base_point=(0, 0, 0))
    good.add_line((0, 0), (10, 0))
    bad_instance = document.modelspace().add_blockref("SubtleSpline", (0, 0))
    good_instance = document.modelspace().add_blockref("Good", (20, 0))
    document.groups.new("Mixed").set_data((bad_instance, good_instance))
    path = tmp_path / f"subtle-spline-{difference}.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert [item.name for item in result.block_definitions] == ["Good"]
    assert len(result.block_instances) == 1
    assert len(result.groups) == 1 and len(result.groups[0].members) == 1
    assert any(
        "SubtleSpline" in warning and "样条" in warning for warning in result.report.warnings
    )
    assert any("组 Mixed" in warning and "无法" in warning for warning in result.report.warnings)


@pytest.mark.parametrize("count", [5, 6, 7])
def test_external_uniform_spline_block_preserves_supported_control_points(
    tmp_path: Path, count: int
) -> None:
    from mycad.core.sketch import SplineEntity
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    block = document.blocks.new("UniformSpline", base_point=(0, 0, 0))
    spline = block.add_spline()
    points = [(float(index), float(index % 2)) for index in range(count)]
    spline.set_open_uniform(points)
    document.modelspace().add_blockref("UniformSpline", (0, 0))
    path = tmp_path / f"uniform-spline-{count}.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert len(result.block_definitions) == len(result.block_instances) == 1
    entity = result.block_definitions[0].entities[0]
    assert isinstance(entity, SplineEntity)
    assert entity.control_points_mm == tuple(points)


@pytest.mark.parametrize("count", [6, 10, 17])
def test_spline_block_and_group_survive_actual_dxf_preview_roundtrip(
    tmp_path: Path, count: int
) -> None:
    from mycad import app
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance, expand_block
    from mycad.core.drawing_groups import DrawingGroup
    from mycad.core.drawing_text import TextStyleTable
    from mycad.core.sketch import SplineEntity
    from mycad.formats.dxf_preview import prepare_dxf_output_preview
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    points = tuple((float(index), float(index % 3)) for index in range(count))
    spline = SplineEntity(uuid4().hex, points)
    definition = BlockDefinition(uuid4().hex, "Spline", (spline,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (4, 5), 27, 2)
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    group = DrawingGroup(uuid4().hex, (DrawingObjectRef("block_instance", instance.instance_id),))
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    preview = prepare_dxf_output_preview(services.kernel)
    path = tmp_path / f"spline-{count}.dxf"
    path.write_bytes(preview.dxf_bytes)
    restored = read_sketch_dxf(path)
    assert (
        len(restored.block_definitions)
        == len(restored.block_instances)
        == len(restored.groups)
        == 1
    )
    restored_instance = restored.block_instances[0]
    assert restored.groups[0].members == (
        DrawingObjectRef("block_instance", restored_instance.instance_id),
    )
    actual = expand_block(
        restored.block_definitions[0], restored_instance, restored.text_styles or TextStyleTable()
    ).entities[0]
    expected = expand_block(definition, instance, TextStyleTable()).entities[0]
    assert isinstance(actual, SplineEntity) and isinstance(expected, SplineEntity)
    for got, want in zip(actual.control_points_mm, expected.control_points_mm, strict=True):
        assert got == pytest.approx(want)
    assert actual.knots == expected.knots


@pytest.mark.parametrize("weight", [0.25, 2.0, 1e100])
def test_external_uniform_spline_block_accepts_equal_positive_weights(
    tmp_path: Path, weight: float
) -> None:
    from mycad.core.sketch import SplineEntity
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    block = document.blocks.new("EquivalentSpline", base_point=(0, 0, 0))
    spline = block.add_spline()
    points = [(0.0, 0.0), (1.0, 4.0), (2.0, 3.0), (3.0, 4.0), (4.0, 0.0)]
    spline.set_open_uniform(points)
    spline.weights = [weight] * len(points)
    instance = document.modelspace().add_blockref("EquivalentSpline", (0, 0))
    document.groups.new("SplineGroup").set_data((instance,))
    path = tmp_path / f"equal-weight-{weight}.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert len(result.block_definitions) == len(result.block_instances) == 1
    curve = result.block_definitions[0].entities[0]
    assert isinstance(curve, SplineEntity) and curve.control_points_mm == tuple(points)
    assert len(result.groups) == 1
    assert result.groups[0].members == (
        DrawingObjectRef("block_instance", result.block_instances[0].instance_id),
    )
    assert not any("EquivalentSpline" in warning for warning in result.report.warnings)


@pytest.mark.parametrize("weight", [0.0, -2.0])
def test_external_uniform_spline_block_rejects_nonpositive_equal_weights(
    tmp_path: Path, weight: float
) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    block = document.blocks.new("InvalidWeight", base_point=(0, 0, 0))
    spline = block.add_spline()
    spline.set_open_uniform([(0, 0), (1, 4), (2, 3), (3, 0)])
    spline.weights = [weight] * 4
    document.modelspace().add_blockref("InvalidWeight", (0, 0))
    document.modelspace().add_line((0, 0), (1, 0))
    path = tmp_path / f"nonpositive-{weight}.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert result.block_instances == () and result.block_definitions == ()
    assert any(
        "InvalidWeight" in warning and "非正" in warning for warning in result.report.warnings
    )


def test_external_nearly_closed_ellipse_block_keeps_its_arc_gap(tmp_path: Path) -> None:
    import math

    from mycad.core.sketch import EllipseEntity
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    block = document.blocks.new("Gap", base_point=(0, 0, 0))
    block.add_ellipse(
        (0, 0), major_axis=(1e12, 0), ratio=0.5, start_param=0, end_param=math.tau - 5e-10
    )
    instance = document.modelspace().add_blockref("Gap", (0, 0))
    document.groups.new("G").set_data((instance,))
    path = tmp_path / "ellipse-gap.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert len(result.block_definitions) == len(result.block_instances) == len(result.groups) == 1
    ellipse = result.block_definitions[0].entities[0]
    assert isinstance(ellipse, EllipseEntity) and not ellipse.closed
    assert ellipse.point_at(1)[1] == pytest.approx(-250.0, abs=0.01)
    assert result.groups[0].members == (
        DrawingObjectRef("block_instance", result.block_instances[0].instance_id),
    )


@pytest.mark.parametrize("sweep", [360.0, -360.0, 359.99999997, -359.99999997])
def test_ellipse_block_preview_roundtrip_preserves_open_or_closed_sweep(
    tmp_path: Path, sweep: float
) -> None:
    from mycad import app
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.drawing_groups import DrawingGroup
    from mycad.core.sketch import EllipseEntity
    from mycad.formats.dxf_preview import prepare_dxf_output_preview
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    ellipse = EllipseEntity(uuid4().hex, (0, 0), 1e8, 5e7, 0, 0, sweep)
    definition = BlockDefinition(uuid4().hex, "Ellipse", (ellipse,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (4, 5))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    group = DrawingGroup(uuid4().hex, (DrawingObjectRef("block_instance", instance.instance_id),))
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    preview = prepare_dxf_output_preview(services.kernel)
    path = tmp_path / f"ellipse-{sweep}.dxf"
    path.write_bytes(preview.dxf_bytes)
    result = read_sketch_dxf(path)
    assert len(result.block_definitions) == len(result.block_instances) == len(result.groups) == 1
    restored = result.block_definitions[0].entities[0]
    assert isinstance(restored, EllipseEntity)
    assert restored.closed == ellipse.closed
    assert restored.sweep_angle_deg == pytest.approx(ellipse.sweep_angle_deg, abs=1e-12)
    assert restored.point_at(1) == pytest.approx(ellipse.point_at(1), abs=1e-7)
    assert result.groups[0].members == (
        DrawingObjectRef("block_instance", result.block_instances[0].instance_id),
    )


def test_external_block_rejects_ellipse_sweep_beyond_one_turn(tmp_path: Path) -> None:
    import math

    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    block = document.blocks.new("InvalidArc", base_point=(0, 0, 0))
    block.add_ellipse(
        (0, 0), major_axis=(1e12, 0), ratio=0.5, start_param=0, end_param=math.tau + 5e-10
    )
    bad = document.modelspace().add_blockref("InvalidArc", (0, 0))
    document.blocks.new("Good", base_point=(0, 0, 0)).add_line((0, 0), (1, 0))
    good = document.modelspace().add_blockref("Good", (10, 0))
    document.groups.new("Mixed").set_data((bad, good))
    path = tmp_path / "ellipse-invalid-sweep.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert [item.name for item in result.block_definitions] == ["Good"]
    assert len(result.block_instances) == 1
    assert len(result.groups) == 1 and len(result.groups[0].members) == 1
    assert any(
        "InvalidArc" in warning and "参数范围" in warning for warning in result.report.warnings
    )


def test_external_full_ellipse_block_preserves_nonzero_parameter_seam(tmp_path: Path) -> None:
    import math

    from mycad.core.sketch import EllipseEntity
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    block = document.blocks.new("Full", base_point=(0, 0, 0))
    block.add_ellipse(
        (0, 0), major_axis=(10, 0), ratio=0.5, start_param=100.0, end_param=100.0 + math.tau
    )
    instance = document.modelspace().add_blockref("Full", (0, 0))
    document.groups.new("G").set_data((instance,))
    path = tmp_path / "ellipse-full-offset.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert len(result.block_definitions) == len(result.block_instances) == len(result.groups) == 1
    ellipse = result.block_definitions[0].entities[0]
    assert isinstance(ellipse, EllipseEntity) and ellipse.closed
    assert ellipse.point_at(0) == pytest.approx((10 * math.cos(100), 5 * math.sin(100)))


def test_external_short_ellipse_arc_block_is_not_treated_as_empty(tmp_path: Path) -> None:
    from mycad.core.sketch import EllipseEntity
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    block = document.blocks.new("ShortArc", base_point=(0, 0, 0))
    block.add_ellipse((0, 0), major_axis=(1e12, 0), ratio=0.5, start_param=0, end_param=5e-11)
    instance = document.modelspace().add_blockref("ShortArc", (0, 0))
    document.groups.new("G").set_data((instance,))
    path = tmp_path / "short-ellipse.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert len(result.block_definitions) == len(result.block_instances) == len(result.groups) == 1
    ellipse = result.block_definitions[0].entities[0]
    assert isinstance(ellipse, EllipseEntity) and not ellipse.closed
    assert ellipse.point_at(1)[1] == pytest.approx(25.0)
    assert result.groups[0].members == (
        DrawingObjectRef("block_instance", result.block_instances[0].instance_id),
    )


@pytest.mark.parametrize("direction", [1, -1])
def test_short_ellipse_arc_block_roundtrips_actual_preview_bytes(
    tmp_path: Path, direction: int
) -> None:
    import math

    from mycad import app
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.drawing_groups import DrawingGroup
    from mycad.core.sketch import EllipseEntity
    from mycad.formats.dxf_preview import prepare_dxf_output_preview
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    ellipse = EllipseEntity(uuid4().hex, (0, 0), 1e12, 5e11, 0, 0, direction * math.degrees(5e-11))
    definition = BlockDefinition(uuid4().hex, "ShortArc", (ellipse,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (4, 5))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    group = DrawingGroup(uuid4().hex, (DrawingObjectRef("block_instance", instance.instance_id),))
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    preview = prepare_dxf_output_preview(services.kernel)
    path = tmp_path / f"short-arc-{direction}.dxf"
    path.write_bytes(preview.dxf_bytes)
    result = read_sketch_dxf(path)
    assert len(result.block_definitions) == len(result.block_instances) == len(result.groups) == 1
    restored = result.block_definitions[0].entities[0]
    assert isinstance(restored, EllipseEntity) and not restored.closed
    assert restored.point_at(0) == pytest.approx(ellipse.point_at(0), abs=1e-4)
    assert restored.point_at(1) == pytest.approx(ellipse.point_at(1), abs=1e-4)
    assert result.groups[0].members == (
        DrawingObjectRef("block_instance", result.block_instances[0].instance_id),
    )


@pytest.mark.parametrize("end", [0.0, 1e-17])
def test_external_block_rejects_empty_or_unrepresentable_ellipse_arc(
    tmp_path: Path, end: float
) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    bad = document.blocks.new("EmptyArc", base_point=(0, 0, 0))
    bad.add_ellipse((0, 0), major_axis=(1e12, 0), ratio=0.5, start_param=0, end_param=end)
    document.blocks.new("Good", base_point=(0, 0, 0)).add_line((0, 0), (1, 0))
    bad_instance = document.modelspace().add_blockref("EmptyArc", (0, 0))
    good_instance = document.modelspace().add_blockref("Good", (10, 0))
    document.groups.new("Mixed").set_data((bad_instance, good_instance))
    path = tmp_path / f"empty-arc-{end}.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert [item.name for item in result.block_definitions] == ["Good"]
    assert len(result.block_instances) == len(result.groups) == 1
    assert len(result.groups[0].members) == 1
    assert any("EmptyArc" in warning and "未导入" in warning for warning in result.report.warnings)


def test_external_block_rejects_slightly_out_of_plane_mtext_direction(tmp_path: Path) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    bad = document.blocks.new("TiltedText", base_point=(0, 0, 0))
    bad.add_mtext(
        "Text",
        dxfattribs={
            "char_height": 1e12,
            "line_spacing_style": 2,
            "text_direction": (1, 0, 5e-10),
        },
    )
    document.blocks.new("Good", base_point=(0, 0, 0)).add_line((0, 0), (1, 0))
    bad_instance = document.modelspace().add_blockref("TiltedText", (0, 0))
    good_instance = document.modelspace().add_blockref("Good", (10, 0))
    document.groups.new("Mixed").set_data((bad_instance, good_instance))
    path = tmp_path / "tilted-text-direction.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert [item.name for item in result.block_definitions] == ["Good"]
    assert len(result.block_instances) == len(result.groups) == 1
    assert len(result.groups[0].members) == 1
    assert any("TiltedText" in warning and "方向" in warning for warning in result.report.warnings)
    assert any("组 Mixed" in warning and "无法" in warning for warning in result.report.warnings)


def test_external_block_accepts_small_nonzero_planar_mtext_direction(tmp_path: Path) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    block = document.blocks.new("Text", base_point=(0, 0, 0))
    text = block.add_mtext(
        "Label",
        dxfattribs={"char_height": 2, "line_spacing_style": 2, "text_direction": (1, 1, 0)},
    )
    instance = document.modelspace().add_blockref("Text", (0, 0))
    document.groups.new("G").set_data((instance,))
    path = tmp_path / "tiny-planar-direction.dxf"
    document.saveas(path)
    raw = path.read_text(encoding="utf-8")
    start = raw.index(f"\n  5\n{text.dxf.handle}\n")
    end = raw.index("\n  0\n", start)
    entity = raw[start:end]
    assert "\n 11\n1.0\n" in entity and "\n 21\n1.0\n" in entity
    entity = entity.replace("\n 11\n1.0\n", "\n 11\n1e-200\n")
    entity = entity.replace("\n 21\n1.0\n", "\n 21\n1e-200\n")
    path.write_text(raw[:start] + entity + raw[end:], encoding="utf-8")
    result = read_sketch_dxf(path)
    assert len(result.block_definitions) == len(result.block_instances) == len(result.groups) == 1
    assert result.block_definitions[0].texts[0].rotation_deg == pytest.approx(45)
    assert result.groups[0].members == (
        DrawingObjectRef("block_instance", result.block_instances[0].instance_id),
    )


@pytest.mark.parametrize("kind", ["line", "polyline", "text", "mtext", "base", "insert"])
def test_external_block_rejects_small_nonzero_height_in_any_component(
    tmp_path: Path, kind: str
) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    bad = document.blocks.new("Elevated", base_point=(0, 0, 5e-8) if kind == "base" else (0, 0, 0))
    if kind == "line":
        add_line = cast("Callable[..., _Entity]", bad.add_line)
        add_line((0, 0, 5e-8), (1, 0, 5e-8))
    elif kind == "polyline":
        bad.add_lwpolyline(((0, 0), (1, 0)), dxfattribs={"elevation": 5e-8})
    elif kind == "text":
        bad.add_text("Label", dxfattribs={"height": 1, "insert": (0, 0, 5e-10)})
    elif kind == "mtext":
        bad.add_mtext(
            "Label", dxfattribs={"char_height": 1, "line_spacing_style": 2, "insert": (0, 0, 5e-10)}
        )
    else:
        bad.add_line((0, 0), (1, 0))
    good = document.blocks.new("Good", base_point=(0, 0, 0))
    good.add_line((0, 0), (1, 0))
    add_blockref = cast("Callable[..., _Entity]", document.modelspace().add_blockref)
    bad_insert = add_blockref(
        "Elevated",
        (0, 0, 5e-8) if kind == "insert" else (0, 0),
        dxfattribs={"xscale": 1e10, "yscale": 1e10},
    )
    good_insert = document.modelspace().add_blockref("Good", (10, 0))
    document.groups.new("Mixed").set_data((bad_insert, good_insert))
    path = tmp_path / f"elevated-{kind}.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert [item.name for item in result.block_definitions] == ["Good"]
    assert len(result.block_instances) == len(result.groups) == 1
    assert len(result.groups[0].members) == 1
    assert any("Elevated" in warning and "未导入" in warning for warning in result.report.warnings)


def test_external_block_coplanar_with_nonzero_base_height_is_flat_after_insertion(
    tmp_path: Path,
) -> None:
    from mycad.core.sketch import (
        CircleEntity,
        EllipseEntity,
        LineEntity,
        PolylineEntity,
        SplineEntity,
    )
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    block = document.blocks.new("Plane", base_point=(10, 20, 7))
    add_line = cast("Callable[..., _Entity]", block.add_line)
    add_line((10, 20, 7), (15, 20, 7))
    add_circle = cast("Callable[..., _Entity]", block.add_circle)
    add_circle((12, 22, 7), 1)
    block.add_lwpolyline(((10, 20), (12, 20)), dxfattribs={"elevation": 7})
    add_ellipse = cast("Callable[..., _Entity]", block.add_ellipse)
    add_ellipse((12, 22, 7), major_axis=(2, 0, 0), ratio=0.5, start_param=0, end_param=1)
    spline = block.add_spline()
    set_points = cast("Callable[..., None]", spline.set_open_uniform)
    set_points([(10, 20, 7), (11, 21, 7), (12, 21, 7), (13, 20, 7)])
    block.add_text("Label", dxfattribs={"height": 2, "insert": (10, 21, 7)})
    block.add_mtext(
        "Note", dxfattribs={"char_height": 2, "line_spacing_style": 2, "insert": (11, 21, 7)}
    )
    instance = document.modelspace().add_blockref("Plane", (3, 4))
    document.groups.new("G").set_data((instance,))
    path = tmp_path / "block-base-plane.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert len(result.block_definitions) == len(result.block_instances) == len(result.groups) == 1
    definition = result.block_definitions[0]
    line = definition.entities[0]
    assert isinstance(line, LineEntity) and line.start_mm == (0, 0) and line.end_mm == (5, 0)
    assert {type(item) for item in definition.entities} == {
        LineEntity,
        CircleEntity,
        EllipseEntity,
        PolylineEntity,
        SplineEntity,
    }
    assert definition.texts[0].position_mm == (0, 1)
    assert definition.texts[1].position_mm == (1, 1)
    assert result.block_instances[0].insertion_mm == (3, 4)
    assert result.groups[0].members == (
        DrawingObjectRef("block_instance", result.block_instances[0].instance_id),
    )


def test_nonzero_base_plane_block_units_transform_and_dxf_roundtrip(tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.drawing_blocks import expand_block
    from mycad.core.drawing_text import TextStyleTable
    from mycad.core.persistence import save_document
    from mycad.formats.dxf_collection_import import prepare_dxf_collection_import
    from mycad.formats.dxf_preview import prepare_dxf_output_preview
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=1)
    block = document.blocks.new("Plane", base_point=(1, 2, 7))
    add_line = cast("Callable[..., _Entity]", block.add_line)
    add_line((1, 2, 7), (2, 2, 7))
    block.add_text("Label", dxfattribs={"height": 1, "insert": (1, 3, 7)})
    instance = document.modelspace().add_blockref(
        "Plane", (3, 4), dxfattribs={"xscale": 2, "yscale": 2, "rotation": 90}
    )
    document.groups.new("G").set_data((instance,))
    path = tmp_path / "inch-plane.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert (
        len(imported.block_definitions)
        == len(imported.block_instances)
        == len(imported.groups)
        == 1
    )
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    operation = prepare_dxf_collection_import(
        imported, app.drawing_collection_snapshot(services)
    ).operation
    loaded.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    original = app.drawing_collection_snapshot(services)
    expanded = expand_block(
        original.block_definitions[0], original.block_instances[0], original.text_styles
    )
    line = expanded.entities[0]
    assert isinstance(line, LineEntity)
    assert line.start_mm == pytest.approx((76.2, 101.6))
    assert line.end_mm == pytest.approx((76.2, 152.4))
    assert expanded.texts[0].position_mm == pytest.approx((25.4, 101.6))
    preview = prepare_dxf_output_preview(services.kernel)
    out = tmp_path / "normalized.dxf"
    out.write_bytes(preview.dxf_bytes)
    restored = read_sketch_dxf(out)
    assert (
        len(restored.block_definitions)
        == len(restored.block_instances)
        == len(restored.groups)
        == 1
    )
    result = expand_block(
        restored.block_definitions[0],
        restored.block_instances[0],
        restored.text_styles or TextStyleTable(),
    )
    copied_line = result.entities[0]
    assert isinstance(copied_line, LineEntity)
    assert copied_line.start_mm == pytest.approx(line.start_mm)
    assert copied_line.end_mm == pytest.approx(line.end_mm)
    assert result.texts[0].position_mm == pytest.approx(expanded.texts[0].position_mm)
    assert restored.groups[0].members == (
        DrawingObjectRef("block_instance", restored.block_instances[0].instance_id),
    )
    native = tmp_path / "plane.my2d"
    save_document(loaded.document, native)
    reopened = app.open_app_document(services, native)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_block_instances == () and services.kernel.drawing_groups == ()
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == original


def test_external_block_with_compensated_height_is_in_drawing_plane(tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.drawing_blocks import expand_block
    from mycad.core.drawing_text import TextStyleTable
    from mycad.core.persistence import save_document
    from mycad.formats.dxf_collection_import import prepare_dxf_collection_import
    from mycad.formats.dxf_preview import prepare_dxf_output_preview
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=1)
    block = document.blocks.new("Compensated", base_point=(1, 2, 7))
    add_line = cast("Callable[..., _Entity]", block.add_line)
    add_line((1, 2, 8), (2, 2, 8))
    block.add_text("Label", dxfattribs={"height": 1, "insert": (1, 3, 8)})
    add_blockref = cast("Callable[..., _Entity]", document.modelspace().add_blockref)
    instance = add_blockref(
        "Compensated",
        (3, 4, -2),
        dxfattribs={"xscale": 2, "yscale": 2, "zscale": 2, "rotation": 90},
    )
    invalid = add_blockref(
        "Compensated", (5, 6, 0), dxfattribs={"xscale": 2, "yscale": 2, "zscale": 2}
    )
    another = add_blockref(
        "Compensated", (7, 8, -3), dxfattribs={"xscale": 2, "yscale": 2, "zscale": 3}
    )
    document.groups.new("G").set_data((instance, invalid, another))
    path = tmp_path / "compensated-height.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert len(result.block_definitions) == len(result.groups) == 1
    assert len(result.block_instances) == 2
    expanded = expand_block(
        result.block_definitions[0],
        result.block_instances[0],
        result.text_styles or TextStyleTable(),
    )
    line = expanded.entities[0]
    assert isinstance(line, LineEntity)
    assert line.start_mm == pytest.approx((76.2, 101.6))
    assert line.end_mm == pytest.approx((76.2, 152.4))
    assert expanded.texts[0].position_mm == pytest.approx((25.4, 101.6))
    assert set(result.groups[0].members) == {
        DrawingObjectRef("block_instance", item.instance_id) for item in result.block_instances
    }
    assert any("图纸 XY 平面" in warning for warning in result.report.warnings)
    assert any("组 G" in warning and "无法" in warning for warning in result.report.warnings)
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    prepared = prepare_dxf_collection_import(result, app.drawing_collection_snapshot(services))
    loaded.bus.execute(prepared.operation.command_id, prepared.operation.params, "local", version=1)
    first = app.drawing_collection_snapshot(services)
    repeated = prepare_dxf_collection_import(result, first)
    assert any("块名称冲突" in warning for warning in repeated.warnings)
    assert any("组名称冲突" in warning for warning in repeated.warnings)
    loaded.bus.execute(repeated.operation.command_id, repeated.operation.params, "local", version=1)
    snapshot = app.drawing_collection_snapshot(services)
    assert len(snapshot.block_definitions) == len(snapshot.groups) == 2
    assert len(snapshot.block_instances) == 4
    assert len({item.instance_id for item in snapshot.block_instances}) == 4
    preview = prepare_dxf_output_preview(services.kernel)
    output = tmp_path / "compensated-roundtrip.dxf"
    output.write_bytes(preview.dxf_bytes)
    restored = read_sketch_dxf(output)
    assert len(restored.block_definitions) == len(restored.groups) == 2
    assert len(restored.block_instances) == 4
    by_id = {definition.definition_id: definition for definition in restored.block_definitions}
    restored_instances = {item.instance_id: item for item in restored.block_instances}
    for group in restored.groups:
        assert len(group.members) == 2
        for ref in group.members:
            restored_instance = restored_instances[ref.object_id]
            geometry = expand_block(
                by_id[restored_instance.definition_id],
                restored_instance,
                restored.text_styles or TextStyleTable(),
            )
            restored_line = geometry.entities[0]
            assert isinstance(restored_line, LineEntity)
            if restored_instance.rotation_deg == 90:
                assert restored_line.start_mm == pytest.approx((76.2, 101.6))
                assert restored_line.end_mm == pytest.approx((76.2, 152.4))
                assert geometry.texts[0].position_mm == pytest.approx((25.4, 101.6))
    native = tmp_path / "compensated-repeated.my2d"
    save_document(loaded.document, native)
    reopened = app.open_app_document(services, native)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == first
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == snapshot


def test_external_block_imports_planar_legacy_polyline_with_bulge(tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.sketch import PolylineEntity
    from mycad.formats.dxf_collection_import import prepare_dxf_collection_import
    from mycad.formats.dxf_preview import prepare_dxf_output_preview
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    block = document.blocks.new("Legacy", base_point=(10, 20, 7))
    add_polyline = block.add_polyline2d
    add_polyline(
        [(10, 20, 0.5), (12, 20, 0.0), (12, 22, 0.0)],
        format="xyb",
        close=True,
        dxfattribs={"elevation": (0, 0, 7)},
    )
    instance = document.modelspace().add_blockref("Legacy", (3, 4))
    document.groups.new("LegacyGroup").set_data((instance,))
    path = tmp_path / "legacy-block.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert len(result.block_definitions) == len(result.block_instances) == len(result.groups) == 1
    polyline = result.block_definitions[0].entities[0]
    assert isinstance(polyline, PolylineEntity)
    assert polyline.points_mm == ((0, 0), (2, 0), (2, 2))
    assert polyline.closed and polyline.bulges == (0.5, 0.0, 0.0)
    assert result.groups[0].members[0].object_id == result.block_instances[0].instance_id
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    operation = prepare_dxf_collection_import(
        result, app.drawing_collection_snapshot(services)
    ).operation
    loaded.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    output = tmp_path / "normalized-legacy.dxf"
    output.write_bytes(prepare_dxf_output_preview(services.kernel).dxf_bytes)
    restored = read_sketch_dxf(output)
    assert len(restored.groups) == len(restored.block_instances) == 1
    restored_polyline = restored.block_definitions[0].entities[0]
    assert isinstance(restored_polyline, PolylineEntity)
    assert restored_polyline.points_mm == polyline.points_mm
    assert restored_polyline.bulges == polyline.bulges
    loaded.bus.undo_operation()
    assert services.kernel.drawing_block_definitions == ()


@pytest.mark.parametrize(
    "kind",
    (
        "width",
        "vertex_width",
        "vertex_fitted",
        "vertex_height",
        "unused_bulge",
        "fitted",
        "three_d",
        "tilted",
        "off_plane",
    ),
)
def test_external_block_rejects_unsupported_legacy_polyline_whole(
    tmp_path: Path, kind: str
) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    block = document.blocks.new("BadLegacy", base_point=(0, 0, 0))
    block.add_line((0, 0), (1, 0))
    attributes: dict[str, object] = {}
    if kind == "width":
        attributes["default_start_width"] = 0.2
    elif kind == "fitted":
        attributes["flags"] = 2
    elif kind == "tilted":
        attributes["extrusion"] = (0, 1e-6, 1)
    elif kind == "off_plane":
        attributes["elevation"] = (0, 0, 1)
    method = "add_polyline3d" if kind == "three_d" else "add_polyline2d"
    add_polyline = cast("Callable[..., object]", getattr(block, method))
    polyline = cast("Any", add_polyline([(0, 0, 0), (1, 1, 0)], dxfattribs=attributes))
    if kind == "vertex_width":
        polyline.vertices[0].dxf.start_width = 0.2
    elif kind == "vertex_fitted":
        polyline.vertices[0].dxf.flags = 2
    elif kind == "vertex_height":
        polyline.vertices[0].dxf.location = (0, 0, 1)
    elif kind == "unused_bulge":
        polyline.vertices[-1].dxf.bulge = 0.5
    bad = document.modelspace().add_blockref("BadLegacy", (0, 0))
    good_block = document.blocks.new("Good", base_point=(0, 0, 0))
    good_block.add_line((0, 0), (1, 0))
    good = document.modelspace().add_blockref("Good", (5, 0))
    document.groups.new("Mixed").set_data((bad, good))
    path = tmp_path / f"legacy-{kind}.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert tuple(definition.name for definition in result.block_definitions) == ("Good",)
    assert len(result.block_instances) == 1
    assert len(result.groups) == 1 and len(result.groups[0].members) == 1
    assert any("BadLegacy" in warning for warning in result.report.warnings)
    assert any("组" in warning for warning in result.report.warnings)


def test_external_block_imports_open_legacy_polyline_with_negative_bulge(tmp_path: Path) -> None:
    from mycad.core.sketch import PolylineEntity
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    block = document.blocks.new("LegacyOpen", base_point=(0, 0, 0))
    block.add_polyline2d([(0, 0, -0.5), (4, 0, 0), (4, 3, 0)], format="xyb")
    document.modelspace().add_blockref("LegacyOpen", (1, 2))
    path = tmp_path / "legacy-open.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert len(result.block_definitions) == len(result.block_instances) == 1
    polyline = result.block_definitions[0].entities[0]
    assert isinstance(polyline, PolylineEntity)
    assert not polyline.closed and polyline.bulges == (-0.5, 0.0)
    assert polyline.points_mm == ((0, 0), (4, 0), (4, 3))


def test_legacy_polyline_block_inch_transform_explode_and_group(tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.drawing_block_transactions import prepare_block_explode
    from mycad.core.drawing_blocks import expand_block
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity
    from mycad.formats.dxf_collection_import import prepare_dxf_collection_import
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=1)
    block = document.blocks.new("LegacyInch", base_point=(1, 2, 7))
    block.add_polyline2d(
        [(1, 2, 0.5), (2, 2, 0), (2, 3, 0)],
        format="xyb",
        close=True,
        dxfattribs={"elevation": (0, 0, 7)},
    )
    instance = document.modelspace().add_blockref(
        "LegacyInch", (3, 4), dxfattribs={"xscale": 2, "yscale": 2, "rotation": 90}
    )
    document.groups.new("LegacyGroup").set_data((instance,))
    path = tmp_path / "inch-legacy.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    operation = prepare_dxf_collection_import(
        imported, app.drawing_collection_snapshot(services)
    ).operation
    loaded.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    before = app.drawing_collection_snapshot(services)
    source = before.block_instances[0]
    expanded = expand_block(before.block_definitions[0], source, before.text_styles).entities[0]
    assert isinstance(expanded, PolylineEntity)
    for actual, expected in zip(
        expanded.points_mm, ((76.2, 101.6), (76.2, 152.4), (25.4, 152.4)), strict=True
    ):
        assert actual == pytest.approx(expected)
    assert expanded.bulges == (0.5, 0, 0)
    operation = prepare_block_explode(before, source.instance_id)
    loaded.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    after = app.drawing_collection_snapshot(services)
    exploded = after.sketches[-1].entities[0]
    assert isinstance(exploded, PolylineEntity)
    assert exploded.points_mm == expanded.points_mm and exploded.bulges == expanded.bulges
    assert exploded.entity_id != expanded.entity_id and len(exploded.point_ids) == 3
    assert after.groups[0].members == (
        DrawingObjectRef("geometry", exploded.entity_id, after.sketches[-1].sketch_id),
    )
    archive = tmp_path / "legacy-exploded.my2d"
    save_document(loaded.document, archive)
    reopened = app.open_app_document(services, archive)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == after


def test_legacy_polyline_vertex_elevation_equal_to_header_is_coplanar(tmp_path: Path) -> None:
    from mycad.core.sketch import PolylineEntity
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    block = document.blocks.new("ElevatedVertices", base_point=(10, 20, 7))
    block.add_polyline2d(
        [(10, 20, 7), (12, 20, 7), (12, 22, 7)],
        close=True,
        dxfattribs={"elevation": (0, 0, 7)},
    )
    add_line = cast("Callable[..., _Entity]", block.add_line)
    add_line((10, 20, 7), (12, 20, 7))
    instance = document.modelspace().add_blockref("ElevatedVertices", (3, 4))
    document.groups.new("ElevatedGroup").set_data((instance,))
    path = tmp_path / "legacy-elevated-vertices.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert len(result.block_definitions) == len(result.block_instances) == len(result.groups) == 1
    polyline = result.block_definitions[0].entities[0]
    assert isinstance(polyline, PolylineEntity)
    assert polyline.points_mm == ((0, 0), (2, 0), (2, 2))


def test_repeated_legacy_polyline_import_remaps_group_and_curve_identities(tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity
    from mycad.formats.dxf_collection_import import prepare_dxf_collection_import
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    sample = (
        Path(__file__).resolve().parents[2]
        / "docs/examples/drawing-collections/external-legacy-polyline.dxf"
    )
    imported = read_sketch_dxf(sample)
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    first_operation = prepare_dxf_collection_import(
        imported, app.drawing_collection_snapshot(services)
    ).operation
    loaded.bus.execute(
        first_operation.command_id, first_operation.params, "local", version=first_operation.version
    )
    first = app.drawing_collection_snapshot(services)
    repeated = prepare_dxf_collection_import(imported, first)
    assert any("块名称冲突" in warning for warning in repeated.warnings)
    assert any("组名称冲突" in warning for warning in repeated.warnings)
    loaded.bus.execute(repeated.operation.command_id, repeated.operation.params, "local", version=1)
    second = app.drawing_collection_snapshot(services)
    assert len(second.block_definitions) == 4 and len(second.block_instances) == 4
    assert len(second.groups) == 2
    assert len({item.name.casefold() for item in second.block_definitions}) == 4
    assert len({item.instance_id for item in second.block_instances}) == 4
    assert set(second.groups[0].members).isdisjoint(second.groups[1].members)
    first_entities = [item.entities[0] for item in second.block_definitions[:2]]
    second_entities = [item.entities[0] for item in second.block_definitions[2:]]
    for original, copied in zip(first_entities, second_entities, strict=True):
        assert isinstance(original, PolylineEntity) and isinstance(copied, PolylineEntity)
        assert original.entity_id != copied.entity_id
        assert original.points_mm == copied.points_mm and original.bulges == copied.bulges
        assert len(original.point_ids) == len(original.points_mm)
        assert len(copied.point_ids) == len(copied.points_mm)
        assert set(original.point_ids).isdisjoint(copied.point_ids)
    path = tmp_path / "legacy-repeated.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == first
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == second


def test_external_group_includes_modelspace_legacy_polyline(tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity
    from mycad.formats.dxf_collection_import import prepare_dxf_collection_import
    from mycad.formats.dxf_preview import prepare_dxf_output_preview
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    model = document.modelspace()
    polyline = cast(
        "_Entity",
        model.add_polyline2d([(0, 0, 0.5), (5, 0, 0), (5, 2, 0)], format="xyb"),
    )
    line = model.add_line((10, 0), (11, 0))
    document.groups.new("MixedLegacy").set_data((polyline, line))
    path = tmp_path / "modelspace-legacy-group.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert len(result.sketch.entities) == 2 and len(result.groups) == 1
    imported = next(item for item in result.sketch.entities if isinstance(item, PolylineEntity))
    assert not imported.closed and imported.bulges == (0.5, 0)
    assert {item.object_id for item in result.groups[0].members} == {
        item.entity_id for item in result.sketch.entities
    }
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    operation = prepare_dxf_collection_import(
        result, app.drawing_collection_snapshot(services)
    ).operation
    loaded.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    snapshot = app.drawing_collection_snapshot(services)
    output = tmp_path / "normalized-modelspace.dxf"
    output.write_bytes(prepare_dxf_output_preview(services.kernel).dxf_bytes)
    restored = read_sketch_dxf(output)
    assert len(restored.sketch.entities) == len(restored.groups[0].members) == 2
    restored_polyline = next(
        item for item in restored.sketch.entities if isinstance(item, PolylineEntity)
    )
    assert restored_polyline.points_mm == imported.points_mm
    assert restored_polyline.bulges == imported.bulges
    archive = tmp_path / "modelspace-group.my2d"
    save_document(loaded.document, archive)
    reopened = app.open_app_document(services, archive)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == () and services.kernel.sketches == ()
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == snapshot


@pytest.mark.parametrize(
    "kind", ("width", "fitted", "three_d", "tilted", "height", "thickness", "hidden")
)
def test_modelspace_group_rejects_unrepresentable_legacy_polyline(
    tmp_path: Path, kind: str
) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    model = document.modelspace()
    attributes: dict[str, object] = {}
    if kind == "width":
        attributes["default_start_width"] = 0.2
    elif kind == "fitted":
        attributes["flags"] = 2
    elif kind == "tilted":
        attributes["extrusion"] = (0, 0.1, 1)
    elif kind == "height":
        attributes["elevation"] = (0, 0, 1)
    elif kind == "thickness":
        attributes["thickness"] = 1
    elif kind == "hidden":
        attributes["invisible"] = 1
    add = model.add_polyline3d if kind == "three_d" else model.add_polyline2d
    polyline = cast("_Entity", add([(0, 0, 0), (2, 0, 0)], dxfattribs=attributes))
    line = model.add_line((4, 0), (5, 0))
    document.groups.new("MixedLegacy").set_data((polyline, line))
    path = tmp_path / f"modelspace-legacy-{kind}.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert len(result.sketch.entities) == len(result.groups) == 1
    assert len(result.groups[0].members) == 1
    assert any("POLYLINE" in warning and "已跳过" in warning for warning in result.report.warnings)
    assert any("MixedLegacy" in warning and "无法" in warning for warning in result.report.warnings)


def test_external_legacy_group_with_block_copies_across_documents(tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.drawing_collection_clipboard import (
        capture_collection_clipboard,
        decode_collection_clipboard,
        encode_collection_clipboard,
        prepare_collection_paste,
    )
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity
    from mycad.formats.dxf_collection_import import prepare_dxf_collection_import
    from mycad.formats.dxf_preview import prepare_dxf_output_preview
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = _new("R2010", units=4)
    block = document.blocks.new("LegacyPart", base_point=(0, 0, 0))
    block.add_line((0, 0), (2, 0))
    block.add_text("Part", dxfattribs={"height": 1, "insert": (0, 1)})
    model = document.modelspace()
    polyline = cast("_Entity", model.add_polyline2d([(0, 0, -0.5), (4, 0, 0)], format="xyb"))
    instance = model.add_blockref("LegacyPart", (5, 0), dxfattribs={"rotation": 30})
    document.groups.new("LegacyAssembly").set_data((polyline, instance))
    path = tmp_path / "mixed-source.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    source_services = app.build_app(discoverers=[])
    source = app.new_workspace_document(source_services, kind="sketch")
    operation = prepare_dxf_collection_import(
        imported, app.drawing_collection_snapshot(source_services)
    ).operation
    source.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    source_snapshot = app.drawing_collection_snapshot(source_services)
    group = source_snapshot.groups[0]
    seed = next(member for member in group.members if member.kind == "geometry")
    payload = capture_collection_clipboard(source_snapshot, (seed,))
    payload = decode_collection_clipboard(encode_collection_clipboard(payload))
    target_services = app.fork_app_services(source_services)
    target = app.new_workspace_document(target_services, kind="sketch")
    operation = prepare_collection_paste(
        payload, app.drawing_collection_snapshot(target_services), (8, 6)
    )
    target.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    pasted = app.drawing_collection_snapshot(target_services)
    assert len(pasted.groups) == len(pasted.block_instances) == len(pasted.block_definitions) == 1
    assert {member.kind for member in pasted.groups[0].members} == {"geometry", "block_instance"}
    assert set(pasted.groups[0].members).isdisjoint(group.members)
    pasted_line = pasted.sketches[0].entities[0]
    assert isinstance(pasted_line, PolylineEntity)
    assert pasted_line.points_mm == ((8, 6), (12, 6)) and pasted_line.bulges == (-0.5,)
    assert pasted.block_definitions[0].texts[0].text == "Part"
    assert pasted.block_instances[0].insertion_mm == (13, 6)
    output = tmp_path / "mixed-copy.dxf"
    output.write_bytes(prepare_dxf_output_preview(target_services.kernel).dxf_bytes)
    restored = read_sketch_dxf(output)
    assert {member.kind for member in restored.groups[0].members} == {"geometry", "block_instance"}
    restored_line = restored.sketch.entities[0]
    assert isinstance(restored_line, PolylineEntity) and restored_line.bulges == (-0.5,)
    archive = tmp_path / "mixed-copy.my2d"
    save_document(target.document, archive)
    reopened = app.open_app_document(target_services, archive)
    reopened.bus.undo_operation()
    assert target_services.kernel.drawing_groups == () and target_services.kernel.sketches == ()
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(target_services) == pasted
    assert app.drawing_collection_snapshot(source_services) == source_snapshot
