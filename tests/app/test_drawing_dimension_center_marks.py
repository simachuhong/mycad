# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Center-mark style history remains replayable and exports to DXF."""

from pathlib import Path
from uuid import uuid4

import ezdxf
import pytest

from mycad import app
from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
from mycad.core.persistence import save_document
from mycad.core.sketch import CircleEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.formats.providers.dxf_provider import write_sketches_dxf


@pytest.mark.parametrize(("kind", "expected"), (("none", 0), ("mark", 3), ("line", -3)))
def test_center_mark_style_history_and_dxf(tmp_path: Path, kind: str, expected: int) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    old = DimensionStyle("旧样式")
    old_mapping = old.to_mapping()
    old_mapping.pop("center_mark")
    old_mapping.pop("center_size")
    for field in (
        "dimension_color",
        "extension_color",
        "text_color",
        "dimension_lineweight",
        "extension_lineweight",
        "dimension_linetype",
        "extension_linetype_first",
        "extension_linetype_second",
        "suppress_extension_first",
        "suppress_extension_second",
        "suppress_dimension_first",
        "suppress_dimension_second",
    ):
        old_mapping.pop(field)
    loaded.bus.execute(
        "drawing.dimension_styles.set",
        {"styles": [old_mapping], "current": "旧样式"},
        "local",
        version=2,
    )
    assert services.kernel.drawing_dimension_styles.current.center_mark == "none"
    style = DimensionStyle("测试", center_mark=kind, center_size=3)
    table = DimensionStyleTable((style,), style.name)
    loaded.bus.execute("drawing.dimension_styles.set", table.to_mapping(), "local")
    assert loaded.document.commands[-1].version == 8
    loaded.bus.undo()
    assert services.kernel.drawing_dimension_styles.current == old
    loaded.bus.redo()
    assert services.kernel.drawing_dimension_styles == table
    circle = CircleEntity(uuid4().hex, (0, 0), 10)
    dimension = SketchConstraint(
        uuid4().hex,
        "radius",
        (SketchGeometryReference(circle.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        position_mm=(20, 0),
        style_name=style.name,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,), (dimension,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    path = tmp_path / "center.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_dimension_styles == table
    dxf = tmp_path / "center.dxf"
    write_sketches_dxf(reopened.kernel.sketches, dxf, dimension_styles=table)
    native = next(
        item for item in ezdxf.readfile(dxf).modelspace() if item.dxftype() == "DIMENSION"
    )
    assert native.override().get("dimcen") == pytest.approx(expected)


def test_dimension_component_colors_export_to_dxf(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    style = DimensionStyle("色彩", dimension_color=1, extension_color=3, text_color=5)
    table = DimensionStyleTable((style,), style.name)
    loaded.bus.execute("drawing.dimension_styles.set", table.to_mapping(), "local")
    assert loaded.document.commands[-1].version == 8
    loaded.bus.undo()
    assert services.kernel.drawing_dimension_styles != table
    loaded.bus.redo()
    circle = CircleEntity(uuid4().hex, (0, 0), 10)
    dimension = SketchConstraint(
        uuid4().hex,
        "radius",
        (SketchGeometryReference(circle.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        position_mm=(20, 0),
        style_name=style.name,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,), (dimension,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    target = tmp_path / "colors.dxf"
    write_sketches_dxf(services.kernel.sketches, target, dimension_styles=table)
    native = next(
        item for item in ezdxf.readfile(target).modelspace() if item.dxftype() == "DIMENSION"
    )
    assert tuple(native.override().get(key) for key in ("dimclrd", "dimclre", "dimclrt")) == (
        1,
        3,
        5,
    )
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    assert read_sketch_dxf(target).dimension_styles == ((dimension.constraint_id, style),)
    path = tmp_path / "colors.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_dimension_styles == table


@pytest.mark.parametrize("version", (3, 4, 5, 6, 7))
def test_legacy_style_replays_with_compatible_defaults(version: int) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    style = DimensionStyle(
        "旧样式",
        center_mark="line",
        text_color=256 if version == 3 else 5,
        dimension_lineweight=35 if version == 5 else -1,
        dimension_linetype="DASHED" if version == 6 else "BYLAYER",
        suppress_extension_first=version == 7,
    )
    mapping = style.to_mapping()
    fields = ["suppress_dimension_first", "suppress_dimension_second"]
    if version < 7:
        fields.extend(("suppress_extension_first", "suppress_extension_second"))
    if version < 6:
        fields.extend(
            ("dimension_linetype", "extension_linetype_first", "extension_linetype_second")
        )
    if version < 5:
        fields.extend(("dimension_lineweight", "extension_lineweight"))
    if version == 3:
        fields.extend(("dimension_color", "extension_color", "text_color"))
    for field in fields:
        mapping.pop(field)
    loaded.bus.execute(
        "drawing.dimension_styles.set",
        {"styles": [mapping], "current": style.name},
        "local",
        version=version,
    )
    assert services.kernel.drawing_dimension_styles.current == style


def test_dimension_lineweights_export_to_dxf_and_recover(tmp_path: Path) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    style = DimensionStyle("线宽", dimension_lineweight=35, extension_lineweight=70)
    table = DimensionStyleTable((style,), style.name)
    loaded.bus.execute("drawing.dimension_styles.set", table.to_mapping(), "local")
    loaded.bus.undo()
    assert services.kernel.drawing_dimension_styles != table
    loaded.bus.redo()
    circle = CircleEntity(uuid4().hex, (0, 0), 10)
    dimension = SketchConstraint(
        uuid4().hex,
        "radius",
        (SketchGeometryReference(circle.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        position_mm=(20, 0),
        style_name=style.name,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,), (dimension,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    target = tmp_path / "lineweight.dxf"
    write_sketches_dxf(services.kernel.sketches, target, dimension_styles=table)
    native = next(
        item for item in ezdxf.readfile(target).modelspace() if item.dxftype() == "DIMENSION"
    )
    assert (native.override().get("dimlwd"), native.override().get("dimlwe")) == (35, 70)
    assert read_sketch_dxf(target).dimension_styles == ((dimension.constraint_id, style),)
    path = tmp_path / "lineweight.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_dimension_styles == table


def test_dimension_linetypes_export_to_dxf_and_recover(tmp_path: Path) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    style = DimensionStyle(
        "线型",
        dimension_linetype="DASHED",
        extension_linetype_first="DOTTED",
        extension_linetype_second="DASHDOT",
    )
    table = DimensionStyleTable((style,), style.name)
    loaded.bus.execute("drawing.dimension_styles.set", table.to_mapping(), "local")
    loaded.bus.undo()
    assert services.kernel.drawing_dimension_styles != table
    loaded.bus.redo()
    circle = CircleEntity(uuid4().hex, (0, 0), 10)
    dim = SketchConstraint(
        uuid4().hex,
        "radius",
        (SketchGeometryReference(circle.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        position_mm=(20, 0),
        style_name=style.name,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,), (dim,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    target = tmp_path / "linetypes.dxf"
    write_sketches_dxf(services.kernel.sketches, target, dimension_styles=table)
    native = next(
        item for item in ezdxf.readfile(target).modelspace() if item.dxftype() == "DIMENSION"
    )
    assert tuple(native.override().get(key) for key in ("dimltype", "dimltex1", "dimltex2")) == (
        "MYCAD_DASHED",
        "MYCAD_DOTTED",
        "MYCAD_DASHDOT",
    )
    assert read_sketch_dxf(target).dimension_styles == ((dim.constraint_id, style),)
    path = tmp_path / "linetypes.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_dimension_styles == table


def test_hidden_extensions_export_and_recover(tmp_path: Path) -> None:
    from mycad.core.sketch import LineEntity
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    style = DimensionStyle("隐藏界线", suppress_extension_first=True)
    table = DimensionStyleTable((style,), style.name)
    loaded.bus.execute("drawing.dimension_styles.set", table.to_mapping(), "local")
    loaded.bus.undo()
    assert services.kernel.drawing_dimension_styles != table
    loaded.bus.redo()
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dim = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        position_mm=(5, 5),
        style_name=style.name,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dim,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    target = tmp_path / "hidden-extension.dxf"
    write_sketches_dxf(services.kernel.sketches, target, dimension_styles=table)
    native = next(
        item for item in ezdxf.readfile(target).modelspace() if item.dxftype() == "DIMENSION"
    )
    assert (native.override().get("dimse1"), native.override().get("dimse2")) == (1, 0)
    assert read_sketch_dxf(target).dimension_styles == ((dim.constraint_id, style),)
    path = tmp_path / "hidden-extension.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_dimension_styles == table


@pytest.mark.parametrize(("first", "second"), ((True, False), (False, True), (True, True)))
def test_hidden_dimension_line_exports_and_recovers(
    tmp_path: Path, first: bool, second: bool
) -> None:
    from mycad.core.sketch import LineEntity
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    style = DimensionStyle(
        "隐藏尺寸线", suppress_dimension_first=first, suppress_dimension_second=second
    )
    table = DimensionStyleTable((style,), style.name)
    loaded.bus.execute("drawing.dimension_styles.set", table.to_mapping(), "local")
    loaded.bus.undo()
    assert services.kernel.drawing_dimension_styles != table
    loaded.bus.redo()
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dim = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        position_mm=(5, 5),
        style_name=style.name,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dim,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    target = tmp_path / "hidden-dimension.dxf"
    write_sketches_dxf(services.kernel.sketches, target, dimension_styles=table)
    document = ezdxf.readfile(target)
    native = next(item for item in document.modelspace() if item.dxftype() == "DIMENSION")
    assert (native.override().get("dimsd1"), native.override().get("dimsd2")) == (
        int(first),
        int(second),
    )
    assert sum(
        item.dxftype() == "INSERT" for item in document.blocks.get(native.dxf.geometry)
    ) == 2 - int(first) - int(second)
    assert read_sketch_dxf(target).dimension_styles == ((dim.constraint_id, style),)
