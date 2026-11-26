# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Render the prepared DXF and export those exact bytes after acceptance."""

from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, cast
from xml.etree import ElementTree

import ezdxf.filemanagement as filemanagement
import pytest

from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
from mycad.formats.dxf_preview import prepare_dxf_output_preview
from mycad.formats.providers.dxf_provider import read_sketch_dxf
from mycad.geom.kernel import BuildKernel


def _new_dxf() -> Any:
    return cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")


def _read_dxf(path: Path) -> Any:
    return cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)


def test_prepared_dxf_includes_dimension_graphics_and_writes_exact_bytes(tmp_path: Path) -> None:
    kernel = BuildKernel()
    identity = "1b1b1b1b-1b1b-4b1b-8b1b-1b1b1b1b1b1b"
    sketch = Sketch(
        "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a",
        WorkPlaneFrame.xy(),
        (LineEntity(identity, (0.0, 0.0), (20.0, 0.0)),),
        (
            SketchConstraint(
                "2c2c2c2c-2c2c-4c2c-8c2c-2c2c2c2c2c2c",
                "length",
                (SketchGeometryReference(identity, "geometry"),),
                20.0,
                "mm",
                driving=False,
            ),
        ),
    )
    kernel.apply("sketch.create", sketch.to_mapping(version=3))
    sketches = kernel.sketches
    preview = prepare_dxf_output_preview(kernel)
    assert preview.report.complete
    assert preview.report.entity_count == 2
    svg = ElementTree.fromstring(preview.svg_bytes)
    assert len(svg.findall(".//{http://www.w3.org/2000/svg}path")) >= 4
    assert b"DIMENSION" in preview.dxf_bytes
    assert list(tmp_path.iterdir()) == []
    path = tmp_path / "prepared.dxf"
    preview.write(path)
    assert path.read_bytes() == preview.dxf_bytes
    assert kernel.sketches == sketches


@pytest.mark.parametrize("graphics", [False, True])
def test_rotated_ordinate_warning_reaches_output_preview(graphics: bool) -> None:
    from uuid import uuid4

    from mycad import app
    from mycad.core.detached_dimension import DetachedDimension

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    dimension = DetachedDimension(uuid4().hex, "ordinate_y", (0, 0), (4, 3), (8, 10), 90, -4)
    loaded.bus.execute(
        "drawing.reference_dimensions.batch", {"add": [dimension.to_mapping()]}, "local"
    )
    preview = prepare_dxf_output_preview(services.kernel, tolerance_graphics=graphics)
    assert any("坐标轴" in warning and "数值" in warning for warning in preview.report.warnings)
    assert "部分软件另存可能改变数值" in str(preview.report)


def test_failed_atomic_export_preserves_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.formats import dxf_preview
    from mycad.formats.dxf_preview import DxfOutputPreview
    from mycad.formats.providers.dxf_provider import DxfExchangeReport

    preview = DxfOutputPreview(
        b"candidate", b"<svg/>", DxfExchangeReport("导出", "AC1024", "mm", 1)
    )
    path = tmp_path / "existing.dxf"
    path.write_bytes(b"original")

    def refuse_replace(_source: object, _target: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(dxf_preview.os, "replace", refuse_replace)
    with pytest.raises(OSError, match="replace failure"):
        preview.write(path)
    assert path.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("graphic", [False, True])
def test_preview_rejects_hidden_vertices_without_legacy_anchor(graphic: bool) -> None:
    from mycad.core.exceptions import ValidationError

    kernel = BuildKernel()
    sketch = Sketch("11" * 16, WorkPlaneFrame.xy(), (LineEntity("22" * 16, (0, 0), (2, 0)),))
    kernel.apply("sketch.create", sketch.to_state_mapping())
    with pytest.raises(ValidationError, match="顶点.*锚点"):
        prepare_dxf_output_preview(
            kernel, tolerance_graphics=graphic, legacy_frame_skipped_vertices={"33" * 16: 1}
        )


def test_graphic_export_reports_legacy_automatic_route_is_not_preserved() -> None:
    from uuid import uuid4

    from mycad import app
    from mycad.core.geometric_tolerance import DatumAttachment, FeatureControlFrame, ToleranceRow

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (-5, 0), (5, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        leader_offsets=((1, -3), (-20, -15)),
        leader_attachment=attachment,
        leader_auto_normal=True,
        leader_auto_route=True,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    preview = prepare_dxf_output_preview(
        services.kernel,
        tolerance_graphics=True,
        legacy_frame_anchors={frame.frame_id: (0, -3)},
        legacy_frame_skipped_vertices={frame.frame_id: 1},
    )
    assert any("自动布线" in warning and "无法" in warning for warning in preview.report.warnings)
    assert not any("仅由本软件扩展数据恢复" in warning for warning in preview.report.warnings)
    assert not any("目标 CAD 排版" in warning for warning in preview.report.warnings)


def test_graphic_export_reports_hidden_normal_constraint_is_not_preserved() -> None:
    from uuid import uuid4

    from mycad import app
    from mycad.core.geometric_tolerance import DatumAttachment, FeatureControlFrame, ToleranceRow

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (-3, -2), (7, -2))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (0, 6),
        leader_target_mm=(2, -2),
        leader_offsets=((2, -3),),
        leader_attachment=attachment,
        leader_auto_normal=True,
        leader_auto_route=True,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    preview = prepare_dxf_output_preview(
        services.kernel,
        tolerance_graphics=True,
        legacy_frame_anchors={frame.frame_id: (5.2, -6)},
        legacy_frame_skipped_vertices={frame.frame_id: 1},
        legacy_frame_bounds={frame.frame_id: (0, 0, 20, 6)},
    )
    assert any(
        "法向约束" in warning and "无法恢复" in warning for warning in preview.report.warnings
    )
    assert any(
        "自动布线" in warning and "无法恢复" in warning for warning in preview.report.warnings
    )
    assert not any("仅由本软件扩展数据恢复" in warning for warning in preview.report.warnings)


@pytest.mark.parametrize(
    "change", ["identity", "rows", "cells", "nan", "zero", "bool", "symbol", "small"]
)
def test_graphic_frame_rejects_invalid_cell_snapshots(change: str) -> None:
    from uuid import uuid4

    from mycad import app
    from mycad.core.geometric_tolerance import FeatureControlFrame, ToleranceRow

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (0, 0))
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    identity = uuid4().hex if change == "identity" else frame.frame_id
    widths: tuple[tuple[float, ...], ...] = ((5.4, 10.0),)
    if change == "rows":
        widths = ((5.4, 10.0), (5.4, 10.0))
    elif change == "cells":
        widths = ((5.4,),)
    elif change == "nan":
        widths = ((5.4, float("nan")),)
    elif change == "zero":
        widths = ((5.4, 0.0),)
    elif change == "bool":
        widths = ((5.4, True),)
    elif change == "symbol":
        widths = ((3.0, 10.0),)
    elif change == "small":
        widths = ((5.4, 1.0),)
    with pytest.raises(ValueError, match="布局"):
        prepare_dxf_output_preview(
            services.kernel, tolerance_graphics=True, graphic_frame_widths={identity: widths}
        )


@pytest.mark.parametrize("with_snapshot", [False, True])
def test_graphic_frame_reports_font_measurement_limit(with_snapshot: bool) -> None:
    from uuid import uuid4

    from mycad import app
    from mycad.core.geometric_tolerance import FeatureControlFrame, ToleranceRow

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (0, 0))
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    widths = {frame.frame_id: ((5.4, 10.0),)} if with_snapshot else None
    preview = prepare_dxf_output_preview(
        services.kernel, tolerance_graphics=True, graphic_frame_widths=widths
    )
    expected = "字体替代" if with_snapshot else "估算字宽"
    assert any(expected in warning for warning in preview.report.warnings)


@pytest.mark.parametrize("change", ["identity", "empty", "nan", "outside", "short"])
def test_graphic_frame_rejects_invalid_glyph_snapshots(change: str) -> None:
    from uuid import uuid4

    from mycad import app
    from mycad.core.geometric_tolerance import FeatureControlFrame, ToleranceRow

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (0, 0))
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    identity = uuid4().hex if change == "identity" else frame.frame_id
    contour = ((6.0, 1.0), (7.0, 1.0), (7.0, 2.0))
    if change == "nan":
        contour = ((float("nan"), 1.0), *contour[1:])
    elif change == "outside":
        contour = ((100.0, 1.0), *contour[1:])
    elif change == "short":
        contour = contour[:2]
    glyphs = () if change == "empty" else ((contour,),)
    with pytest.raises(ValueError, match="字形"):
        prepare_dxf_output_preview(
            services.kernel,
            tolerance_graphics=True,
            graphic_frame_widths={frame.frame_id: ((5.4, 10.0),)},
            graphic_frame_glyphs={identity: glyphs},
        )


def test_multi_sketch_preview_writes_exact_projected_bytes(tmp_path: Path) -> None:
    kernel = BuildKernel()
    first = Sketch("11" * 16, WorkPlaneFrame.xy(), (LineEntity("22" * 16, (0, 0), (2, 0)),))
    frame = WorkPlaneFrame((10, 5, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    second = Sketch("33" * 16, frame, (LineEntity("44" * 16, (0, 0), (3, 0)),))
    for sketch in (first, second):
        kernel.apply("sketch.create", sketch.to_state_mapping())
    before = kernel.sketches
    preview = prepare_dxf_output_preview(kernel)
    assert preview.report.entity_count == 2
    assert any("多个草图" in warning for warning in preview.report.warnings)
    assert (
        len(
            ElementTree.fromstring(preview.svg_bytes).findall(".//{http://www.w3.org/2000/svg}path")
        )
        >= 2
    )
    path = tmp_path / "multi-preview.dxf"
    preview.write(path)
    assert path.read_bytes() == preview.dxf_bytes and kernel.sketches == before
    imported = read_sketch_dxf(path).sketch.entities
    assert isinstance(imported[1], LineEntity) and imported[1].end_mm == pytest.approx((10, 8))


@pytest.mark.parametrize("visible", [True, False])
def test_output_preview_respects_layer_visibility_and_keeps_loss_report(visible: bool) -> None:
    kernel = BuildKernel()
    identity = "1b1b1b1b-1b1b-4b1b-8b1b-1b1b1b1b1b1b"
    sketch = Sketch(
        "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a",
        WorkPlaneFrame.xz(),
        (LineEntity(identity, (0.0, 0.0), (20.0, 0.0), layer_name="custom"),),
        (
            SketchConstraint(
                "2c2c2c2c-2c2c-4c2c-8c2c-2c2c2c2c2c2c",
                "horizontal",
                (SketchGeometryReference(identity, "geometry"),),
                source="inferred",
            ),
        ),
        layers=SketchLayerTable().add(SketchLayer("custom", (230, 30, 40), visible=visible)),
    )
    kernel.apply("sketch.create", sketch.to_mapping(version=3))
    preview = prepare_dxf_output_preview(kernel)
    assert (b"#e61e28" in preview.svg_bytes) is visible
    assert not preview.report.complete
    assert len(preview.report.warnings) == 2
    assert "工作平面" in str(preview.report)
    assert b"LINE" in preview.dxf_bytes  # hidden geometry is retained in exchange
    assert bool(preview.notices) is not visible


def test_native_tolerance_is_rendered_from_exported_bytes() -> None:
    from mycad import app
    from mycad.core.geometric_tolerance import FeatureControlFrame, ToleranceRow

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    frame = FeatureControlFrame("ab" * 16, (ToleranceRow("position", 0.12, 2),), (5, 4), 30)
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    preview = prepare_dxf_output_preview(services.kernel)
    assert b"TOLERANCE" in preview.dxf_bytes
    assert (
        len(
            ElementTree.fromstring(preview.svg_bytes).findall(".//{http://www.w3.org/2000/svg}path")
        )
        >= 4
    )
    assert preview.report.entity_count == 1
    assert any("公差" in notice for notice in preview.notices)
    assert any("LibreCAD" in warning for warning in preview.report.warnings)


def test_tolerance_preview_honors_hidden_drawing_layer() -> None:
    from mycad import app
    from mycad.core.geometric_tolerance import FeatureControlFrame, ToleranceRow

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    layers = services.kernel.drawing_layers.add(SketchLayer("hidden", visible=False))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    frame = FeatureControlFrame(
        "ac" * 16, (ToleranceRow("flatness", 0.2, 1),), (0, 0), layer_name="hidden"
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    preview = prepare_dxf_output_preview(services.kernel)
    assert b"TOLERANCE" in preview.dxf_bytes
    assert any("没有可见图元" in notice for notice in preview.notices)


def test_datum_block_is_in_preview_and_exact_export_bytes(tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    datum = DatumIdentifier("ad" * 16, "A", (3, 5), (3, 0))
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    preview = prepare_dxf_output_preview(services.kernel)
    assert b"INSERT" in preview.dxf_bytes and b"SOLID" in preview.dxf_bytes
    assert (
        len(
            ElementTree.fromstring(preview.svg_bytes).findall(".//{http://www.w3.org/2000/svg}path")
        )
        >= 3
    )
    path = tmp_path / "datum.dxf"
    preview.write(path)
    assert read_sketch_dxf(path).datum_identifiers == (datum,)
    assert any("图形块" in warning for warning in preview.report.warnings)


def test_detached_dimension_has_native_export_and_real_preview() -> None:
    from mycad import app
    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.dimension_tolerance import DimensionTolerance

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    dimension = DetachedDimension(
        "ae" * 16,
        "rotated",
        (0, 0),
        (10, 0),
        (0, 5),
        0,
        10,
        DimensionTolerance("symmetric", 0.1, -0.1),
    )
    loaded.bus.execute(
        "drawing.reference_dimensions.batch", {"add": [dimension.to_mapping()]}, "local"
    )
    preview = prepare_dxf_output_preview(services.kernel)
    assert b"DIMENSION" in preview.dxf_bytes
    assert preview.report.entity_count == 1
    assert (
        len(
            ElementTree.fromstring(preview.svg_bytes).findall(".//{http://www.w3.org/2000/svg}path")
        )
        >= 4
    )


def test_tolerance_preview_text_fits_cells_and_modifier_circles() -> None:
    from ezdxf import bbox

    from mycad.core.geometric_tolerance import DatumReference, ToleranceRow
    from mycad.formats.geometric_tolerance_codec import encode_rows
    from mycad.formats.geometric_tolerance_preview import expand_tolerances_for_preview

    document = _new_dxf()
    space = document.modelspace()
    row = ToleranceRow("position", 0.12, 2, False, "M", (DatumReference("WIDE", modifier="L"),))
    space.new_entity("TOLERANCE", {"insert": (0, 0), "content": encode_rows((row,))})
    assert expand_tolerances_for_preview(document) == (1, 0)
    labels = list(space.query("TEXT"))
    verticals = sorted(
        line.dxf.start.x
        for line in space.query("LINE")
        if abs(line.dxf.start.x - line.dxf.end.x) < 1e-9
        and abs(line.dxf.start.y - line.dxf.end.y) > 5.9
    )
    for text in labels:
        bounds = bbox.extents([text])
        right = next(x for x in verticals if x > text.dxf.insert.x)
        assert bounds.extmax.x < right
    number = next(item for item in labels if item.dxf.text == "0.12")
    first_circle = min(
        (item for item in space.query("CIRCLE") if item.dxf.center.x > 5.4),
        key=lambda item: item.dxf.center.x,
    )
    assert bbox.extents([number]).extmax.x < first_circle.dxf.center.x - first_circle.dxf.radius


def test_wide_font_modifier_fits_tolerance_preview_circle() -> None:
    from ezdxf import bbox

    from mycad.core.geometric_tolerance import ToleranceRow
    from mycad.formats.geometric_tolerance_codec import encode_rows
    from mycad.formats.geometric_tolerance_preview import expand_tolerances_for_preview

    document = _new_dxf()
    document.styles.new("wide", dxfattribs={"font": "txt", "width": 8})
    document.dimstyles.new("wide-dim", dxfattribs={"dimtxsty": "wide", "dimtxt": 3.5})
    space = document.modelspace()
    space.new_entity(
        "TOLERANCE",
        {
            "insert": (0, 0),
            "dimstyle": "wide-dim",
            "content": encode_rows((ToleranceRow("flatness", 0.1, 1, modifier="M"),)),
        },
    )
    assert expand_tolerances_for_preview(document) == (1, 0)
    modifier = next(item for item in space.query("TEXT") if item.dxf.text == "M")
    circle = next(iter(space.query("CIRCLE")))
    bounds = bbox.extents([modifier])
    assert bounds.extmin.x >= circle.dxf.center.x - circle.dxf.radius
    assert bounds.extmax.x <= circle.dxf.center.x + circle.dxf.radius


def test_graphic_export_outlines_wide_text_without_distorting_row() -> None:

    from mycad.core.geometric_tolerance import DatumReference, ToleranceRow
    from mycad.formats.geometric_tolerance_codec import encode_rows
    from mycad.formats.geometric_tolerance_preview import expand_tolerances_for_preview

    document = _new_dxf()
    document.styles.new("wide", dxfattribs={"font": "txt", "width": 3})
    document.dimstyles.new("wide-dim", dxfattribs={"dimtxsty": "wide", "dimtxt": 7})
    space = document.modelspace()
    row = ToleranceRow("position", 0.05, 2, True, "M", (DatumReference("A", modifier="L"),))
    space.new_entity(
        "TOLERANCE", {"insert": (0, 0), "dimstyle": "wide-dim", "content": encode_rows((row,))}
    )
    assert expand_tolerances_for_preview(document, outline_wide_text=True) == (1, 0)
    assert not space.query("TEXT")
    lines = list(space.query("LINE"))
    assert len(lines) > 100
    assert all(
        -12.01 <= point.y <= 0.01 for line in lines for point in (line.dxf.start, line.dxf.end)
    )


def test_wide_graphic_outline_resolves_requested_font_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ezdxf.addons import text2path

    from mycad.core.geometric_tolerance import ToleranceRow
    from mycad.formats.geometric_tolerance_codec import encode_rows
    from mycad.formats.geometric_tolerance_preview import expand_tolerances_for_preview

    document = _new_dxf()
    style = document.styles.new("serif", dxfattribs={"font": "", "width": 2})
    style.set_extended_font_data("DejaVu Serif")
    document.dimstyles.new("serif-dim", dxfattribs={"dimtxsty": "serif", "dimtxt": 3.5})
    space = document.modelspace()
    space.new_entity(
        "TOLERANCE",
        {
            "insert": (0, 0),
            "dimstyle": "serif-dim",
            "content": encode_rows((ToleranceRow("flatness", 0.1, 1),)),
        },
    )
    original = text2path.make_paths_from_str
    families: list[str] = []

    def record(value: str, face: Any, **kwargs: Any) -> Any:
        families.append(face.family)
        return original(value, face, **kwargs)

    monkeypatch.setattr(text2path, "make_paths_from_str", record)
    assert expand_tolerances_for_preview(document, outline_wide_text=True, strict=True) == (1, 0)
    assert families and set(families) == {"DejaVu Serif"}


def test_wide_graphic_outline_rejects_missing_glyph(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from ezdxf.fonts import fonts

    from mycad.core.geometric_tolerance import ToleranceRow
    from mycad.formats.geometric_tolerance_codec import encode_rows
    from mycad.formats.geometric_tolerance_preview import expand_tolerances_for_preview

    document = _new_dxf()
    document.styles.new("wide", dxfattribs={"font": "txt", "width": 2})
    document.dimstyles.new("wide-dim", dxfattribs={"dimtxsty": "wide", "dimtxt": 3.5})
    document.modelspace().new_entity(
        "TOLERANCE",
        {
            "insert": (0, 0),
            "dimstyle": "wide-dim",
            "content": encode_rows((ToleranceRow("flatness", 0.1, 1),)),
        },
    )

    def text_width(text: str) -> float:
        return float(len(text))

    def missing_font(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(glyph_cache=SimpleNamespace(cmap={}), text_width=text_width)

    monkeypatch.setattr(fonts, "make_font", missing_font)
    with pytest.raises(ValueError, match="缺少字符"):
        expand_tolerances_for_preview(document, outline_wide_text=True, strict=True)


@pytest.mark.parametrize("missing", ["file", "family", "shx"])
def test_wide_graphic_outline_rejects_unavailable_font(
    missing: Literal["file", "family", "shx"],
) -> None:

    from mycad.core.geometric_tolerance import ToleranceRow
    from mycad.formats.geometric_tolerance_codec import encode_rows
    from mycad.formats.geometric_tolerance_preview import expand_tolerances_for_preview

    document = _new_dxf()
    style = document.styles.new(
        "unavailable",
        dxfattribs={
            "font": {"file": "MyCAD-not-a-font.ttf", "family": "", "shx": "custom.shx"}[missing],
            "width": 2,
        },
    )
    if missing == "family":
        style.set_extended_font_data("MyCAD-Definitely-Not-Installed")
    document.dimstyles.new("unavailable-dim", dxfattribs={"dimtxsty": "unavailable", "dimtxt": 3.5})
    document.modelspace().new_entity(
        "TOLERANCE",
        {
            "insert": (0, 0),
            "dimstyle": "unavailable-dim",
            "content": encode_rows((ToleranceRow("flatness", 0.1, 1),)),
        },
    )
    with pytest.raises(ValueError, match="字体.*不可用"):
        expand_tolerances_for_preview(document, outline_wide_text=True, strict=True)


def test_graphic_export_does_not_report_discarded_compressed_metadata(tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.geometric_tolerance import DatumReference, FeatureControlFrame, ToleranceRow

    char = "𠀀"
    style = TextStyle(char * 80, char * 500, char * 63, "Bold", char * 63)
    row = ToleranceRow(
        "position", 0.1, 1, datums=(DatumReference("A"), DatumReference("B"), DatumReference("C"))
    )
    frame = FeatureControlFrame("ac" * 16, (row,) * 8, (0, 0), text_style_id=style.style_id)
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((style,), style.style_id).to_mapping(), "local"
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    native = prepare_dxf_output_preview(services.kernel)
    assert any("元数据已压缩" in warning for warning in native.report.warnings)
    graphic = prepare_dxf_output_preview(services.kernel, tolerance_graphics=True)
    assert not any("元数据已压缩" in warning for warning in graphic.report.warnings)
    assert any("不可" in warning and "编辑" in warning for warning in graphic.report.warnings)
    path = tmp_path / "graphic.dxf"
    graphic.write(path)
    assert not read_sketch_dxf(path).tolerance_frames


def test_graphic_tolerance_export_reports_orphaned_surface_indication(tmp_path: Path) -> None:
    from uuid import uuid4

    from mycad import app
    from mycad.core.geometric_tolerance import FeatureControlFrame, SurfaceIndication, ToleranceRow

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    indication = SurfaceIndication((5, 5), (10, 5), 0.5)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -2),
        surface_indication=indication,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    preview = prepare_dxf_output_preview(services.kernel, tolerance_graphics=True)
    assert any("表面指示" in warning for warning in preview.report.warnings)
    path = tmp_path / "surface-indication-graphics.dxf"
    preview.write(path)
    imported = read_sketch_dxf(path)
    assert not imported.tolerance_frames
    assert any("表面指示" in warning for warning in imported.report.warnings)
    assert imported.sketch.entities


def test_graphic_tolerance_export_reports_orphaned_surface_extension(tmp_path: Path) -> None:
    from uuid import uuid4

    from mycad import app
    from mycad.core.geometric_tolerance import DatumAttachment, FeatureControlFrame, ToleranceRow
    from mycad.core.geometric_tolerance_surface_extension import SurfaceExtensionSpec
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(line.entity_id, "geometry"),
        1,
        surface_extension=SurfaceExtensionSpec("end", 5, 1, 2),
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 10),
        leader_target_mm=(15, 0),
        leader_anchor_offset=(0, -2),
        leader_attachment=attachment,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    preview = prepare_dxf_output_preview(services.kernel, tolerance_graphics=True)
    assert any("表面延伸" in warning and "关联" in warning for warning in preview.report.warnings)
    path = tmp_path / "surface-graphics.dxf"
    preview.write(path)
    imported = read_sketch_dxf(path)
    assert not imported.tolerance_frames
    assert any("表面延伸" in warning for warning in imported.report.warnings)
    assert any(
        isinstance(item, LineEntity) and item.start_mm == (11, 0) and item.end_mm == (17, 0)
        for item in imported.sketch.entities
    )


def test_graphic_tolerance_export_warns_of_detached_datum(tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.geometric_tolerance import (
        AnnotationAttachment,
        DatumIdentifier,
        FeatureControlFrame,
        ToleranceRow,
    )

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    frame = FeatureControlFrame("ab" * 16, (ToleranceRow("position", 0.1, 2),), (0, 0))
    datum = DatumIdentifier(
        "cd" * 16,
        "A",
        (10, 10),
        (0, 0),
        annotation_attachment=AnnotationAttachment("frame", frame.frame_id, (0, 0)),
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
        "local",
    )
    preview = prepare_dxf_output_preview(services.kernel, tolerance_graphics=True)
    assert any("附着" in warning and "解除" in warning for warning in preview.report.warnings)
    path = tmp_path / "graphics-detach.dxf"
    preview.write(path)
    imported = read_sketch_dxf(path)
    assert imported.datum_identifiers[0].annotation_attachment is None
    assert any("附着" in warning for warning in imported.report.warnings)


def test_opt_in_graphic_tolerance_export_reports_semantic_loss(tmp_path: Path) -> None:

    from mycad import app
    from mycad.core.geometric_tolerance import DatumReference, FeatureControlFrame, ToleranceRow

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    rows = (
        ToleranceRow("position", 0.1, 1, True, "M", (DatumReference("A"),)),
        ToleranceRow("flatness", 0.05, 2),
    )
    frame = FeatureControlFrame("af" * 16, rows, (5, 4), 30)
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    preview = prepare_dxf_output_preview(services.kernel, tolerance_graphics=True)
    path = tmp_path / "compatibility.dxf"
    preview.write(path)
    assert path.read_bytes() == preview.dxf_bytes
    document = _read_dxf(path)
    assert not document.modelspace().query("TOLERANCE")
    assert document.modelspace().query("LINE") and document.modelspace().query("TEXT")
    assert any("不可" in warning and "编辑" in warning for warning in preview.report.warnings)
    assert not preview.report.complete
    assert ElementTree.fromstring(preview.svg_bytes).findall(".//{http://www.w3.org/2000/svg}path")


@pytest.mark.parametrize("width", [1.0, 2.0])
def test_graphic_datum_compression_warning_matches_output(tmp_path: Path, width: float) -> None:
    from mycad import app
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    style = TextStyle("wide-datum", "字" * 80, "DejaVu Sans", width_factor=width)
    loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((style,), style.style_id).to_mapping(), "local"
    )
    datum = DatumIdentifier("de" * 16, "%^" * 40, (0, 0), (0, -10), text_style_id=style.style_id)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    preview = prepare_dxf_output_preview(services.kernel, tolerance_graphics=True)
    path = tmp_path / "datum-graphics.dxf"
    preview.write(path)
    imported = read_sketch_dxf(path)
    assert bool(imported.datum_identifiers) == (width == 1.0)
    assert any("基准元数据已压缩" in warning for warning in preview.report.warnings) == (
        width == 1.0
    )
    if width != 1.0:
        assert any(
            "基准" in warning and "无法恢复" in warning for warning in preview.report.warnings
        )


def test_graphic_datum_compression_warning_remains_for_unconverted_datum(tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    styles = (
        TextStyle("normal", "字" * 79 + "一", "DejaVu Sans"),
        TextStyle("wide", "字" * 79 + "二", "DejaVu Sans", width_factor=2),
    )
    loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable(styles, "normal").to_mapping(), "local"
    )
    datums = [
        DatumIdentifier("ab" * 16, "%^" * 40, (0, 20), (0, 10), text_style_id="normal"),
        DatumIdentifier("cd" * 16, "%^" * 39 + "%A", (0, 0), (0, -10), text_style_id="wide"),
    ]
    loaded.bus.execute(
        "drawing.tolerance.batch", {"add_datums": [d.to_mapping() for d in datums]}, "local"
    )
    preview = prepare_dxf_output_preview(services.kernel, tolerance_graphics=True)
    path = tmp_path / "mixed-datums.dxf"
    preview.write(path)
    assert [datum.datum_id for datum in read_sketch_dxf(path).datum_identifiers] == [
        datums[0].datum_id
    ]
    assert any("基准元数据已压缩" in warning for warning in preview.report.warnings)
    assert any("基准" in warning and "无法恢复" in warning for warning in preview.report.warnings)


def test_graphic_datum_without_canvas_snapshot_reports_font_substitution_risk() -> None:
    from uuid import uuid4

    from mycad import app
    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (0, -10))
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    preview = prepare_dxf_output_preview(services.kernel, tolerance_graphics=True)
    assert any("未取得画布基准字形快照" in warning for warning in preview.report.warnings)


def test_graphic_export_outlines_wide_datum_and_discloses_lost_metadata(tmp_path: Path) -> None:

    from mycad import app
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    style = TextStyle("wide", "宽字体", "DejaVu Sans", height_mm=7, width_factor=3)
    loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((TextStyle(), style)).to_mapping(), "local"
    )
    default = DatumIdentifier("ab" * 16, "A", (0, 20), (0, 10))
    wide = DatumIdentifier("cd" * 16, "O0A", (0, 0), (0, -10), text_style_id="wide")
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [default.to_mapping(), wide.to_mapping()]},
        "local",
    )
    preview = prepare_dxf_output_preview(services.kernel, tolerance_graphics=True)
    path = tmp_path / "compatibility.dxf"
    preview.write(path)
    document = _read_dxf(path)
    inserts = list(document.modelspace().query("INSERT"))
    assert len(inserts) == 2
    assert inserts[0].has_xdata("MYCAD_DATUM") and not inserts[1].has_xdata("MYCAD_DATUM")
    assert list(document.blocks.get(inserts[0].dxf.name).query("TEXT"))
    assert not list(document.blocks.get(inserts[1].dxf.name).query("TEXT"))
    assert len(document.blocks.get(inserts[1].dxf.name).query("LINE")) > 20
    assert any("基准" in warning and "无法" in warning for warning in preview.report.warnings)
    assert any("空心轮廓" in warning for warning in preview.report.warnings)


@pytest.mark.parametrize(
    "change", ["identity", "stale", "width", "bool", "nan", "outside", "empty", "leader", "arrow"]
)
def test_graphic_datum_rejects_invalid_snapshots(change: str) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad import app
    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.core.geometric_tolerance_geometry import datum_leader_path, datum_triangle
    from mycad.formats.dxf_datum import DatumGraphicSnapshot

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (0, -20))
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    glyphs = ((((1.0, 1.0), (2.0, 1.0), (2.0, 2.0)),),)
    leader = datum_leader_path((0, 0, 10, -10), (0, -20))
    arrow = datum_triangle(leader[-2], leader[-1])
    snapshot = DatumGraphicSnapshot(datum, 10, 10, leader, arrow, glyphs)
    identity = uuid4().hex if change == "identity" else datum.datum_id
    if change == "stale":
        snapshot = replace(snapshot, datum=replace(datum, label="B"))
    elif change == "width":
        snapshot = replace(snapshot, width=-1)
    elif change == "bool":
        snapshot = replace(snapshot, width=True)
    elif change == "nan":
        snapshot = replace(snapshot, glyphs=((((float("nan"), 1.0), (2.0, 1.0), (2.0, 2.0)),),))
    elif change == "outside":
        snapshot = replace(snapshot, glyphs=((((100.0, 1.0), (2.0, 1.0), (2.0, 2.0)),),))
    elif change == "empty":
        snapshot = replace(snapshot, glyphs=())
    elif change == "leader":
        snapshot = replace(snapshot, leader=())
    elif change == "arrow":
        snapshot = replace(snapshot, arrow=((100, 100), *arrow[1:]))
    with pytest.raises(ValueError, match="尺寸" if change == "bool" else "基准图形"):
        prepare_dxf_output_preview(
            services.kernel, tolerance_graphics=True, graphic_datum_snapshots={identity: snapshot}
        )


@pytest.mark.parametrize(
    "change", ["missing", "identity", "stale", "width", "height", "bool", "text"]
)
def test_native_legacy_datum_rejects_invalid_snapshots(change: str) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad import app
    from mycad.core.exceptions import ValidationError
    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.formats.dxf_datum import DatumNativeSnapshot

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (0, -20))
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    snapshot = DatumNativeSnapshot(datum, 10, 10)
    identity = uuid4().hex if change == "identity" else datum.datum_id
    if change == "stale":
        snapshot = replace(snapshot, datum=replace(datum, label="B"))
    elif change == "width":
        snapshot = replace(snapshot, width=-1)
    elif change == "height":
        snapshot = replace(snapshot, height=float("nan"))
    elif change == "bool":
        snapshot = replace(snapshot, width=True)
    elif change == "text":
        snapshot = replace(snapshot, width="not-a-number")
    snapshots = {} if change == "missing" else {identity: snapshot}
    with pytest.raises(ValidationError, match="旧基准布局快照"):
        prepare_dxf_output_preview(services.kernel, legacy_datum_snapshots=snapshots)


def test_native_legacy_datum_without_snapshot_reports_geometry_risk() -> None:
    from uuid import uuid4

    from mycad import app
    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (0, -10))
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    preview = prepare_dxf_output_preview(services.kernel)
    assert any("旧基准框及引线按导出字体估算" in warning for warning in preview.report.warnings)


def test_native_legacy_datum_snapshot_rejects_duplicate_identity_without_overwrite(
    tmp_path: Path,
) -> None:
    from uuid import uuid4

    from mycad.core.exceptions import ValidationError
    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.formats.dxf_datum import DatumNativeSnapshot
    from mycad.formats.providers.dxf_provider import write_sketches_dxf

    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (0, -20))
    snapshot = DatumNativeSnapshot(datum, 10, 10)
    path = tmp_path / "existing.dxf"
    path.write_bytes(b"existing")
    with pytest.raises(ValidationError, match="旧基准布局快照"):
        write_sketches_dxf(
            (),
            path,
            datum_identifiers=(datum, datum),
            legacy_datum_snapshots={datum.datum_id: snapshot},
        )
    assert path.read_bytes() == b"existing"


def test_datum_graphic_snapshot_cannot_be_silently_ignored_in_native_export() -> None:
    from uuid import uuid4

    from mycad import app
    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.formats.dxf_datum import DatumGraphicSnapshot

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (0, -10))
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    snapshot = DatumGraphicSnapshot(datum, 10, 10, (), (), ((((1, 1), (2, 1), (2, 2)),),))
    with pytest.raises(ValueError, match="图形"):
        prepare_dxf_output_preview(
            services.kernel, graphic_datum_snapshots={datum.datum_id: snapshot}
        )


def test_graphic_datum_rejects_stale_shared_box_size() -> None:
    from uuid import uuid4

    from mycad import app
    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.core.geometric_tolerance_geometry import datum_leader_path, datum_triangle
    from mycad.formats.dxf_datum import DatumGraphicSnapshot

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    datum = DatumIdentifier(
        uuid4().hex, "A", (0, 0), (0, -20), layout_mode="shared", box_size_mm=(10, 10)
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    leader = datum_leader_path((0, 0, 11, -10), (0, -20))
    snapshot = DatumGraphicSnapshot(
        datum,
        11,
        10,
        leader,
        datum_triangle(leader[-2], leader[-1]),
        ((((1, 1), (2, 1), (2, 2)),),),
    )
    with pytest.raises(ValueError, match="标注框"):
        prepare_dxf_output_preview(
            services.kernel,
            tolerance_graphics=True,
            graphic_datum_snapshots={datum.datum_id: snapshot},
        )


def test_graphic_export_wide_datum_preserves_literal_special_characters(tmp_path: Path) -> None:
    from ezdxf.fonts import fonts

    from mycad import app
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.formats.font_outline import outline_text_segments

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    style = TextStyle("wide", "宽字体", "DejaVu Sans", height_mm=7, width_factor=2)
    loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((TextStyle(), style)).to_mapping(), "local"
    )
    datum = DatumIdentifier("cd" * 16, "A%^", (0, 0), (0, -20), text_style_id="wide")
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    preview = prepare_dxf_output_preview(services.kernel, tolerance_graphics=True)
    path = tmp_path / "special.dxf"
    preview.write(path)
    document = _read_dxf(path)
    insert = next(iter(document.modelspace().query("INSERT")))
    block = document.blocks.get(insert.dxf.name)
    assert not block.query("TEXT")
    face = fonts.find_best_match(family="DejaVu Sans")
    assert face is not None
    font_name = face.filename
    expected = sum(len(outline_text_segments(char, font_name, 7, 2)) for char in "A%^")
    assert len(block.query("LINE")) == 5 + expected
    assert not insert.has_xdata("MYCAD_DATUM")


def test_graphic_export_wide_datum_rejects_missing_font() -> None:
    from mycad import app
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    style = TextStyle("missing", "缺失字体", "MyCAD-Definitely-Not-Installed", width_factor=2)
    loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((TextStyle(), style)).to_mapping(), "local"
    )
    datum = DatumIdentifier("cd" * 16, "A", (0, 0), (0, -10), text_style_id="missing")
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    with pytest.raises(ValueError, match="基准图形转换失败.*字体.*不可用"):
        prepare_dxf_output_preview(services.kernel, tolerance_graphics=True)


def test_graphic_tolerance_export_preserves_hidden_layer(tmp_path: Path) -> None:

    from mycad import app
    from mycad.core.geometric_tolerance import FeatureControlFrame, ToleranceRow

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    layers = services.kernel.drawing_layers.add(SketchLayer("hidden", visible=False))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    frame = FeatureControlFrame(
        "bc" * 16, (ToleranceRow("flatness", 0.2, 1),), (0, 0), layer_name="hidden"
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    preview = prepare_dxf_output_preview(services.kernel, tolerance_graphics=True)
    path = tmp_path / "hidden-compat.dxf"
    preview.write(path)
    document = _read_dxf(path)
    assert document.layers.get("hidden").is_off()
    assert document.modelspace().query('LINE[layer=="hidden"]')
    assert any("没有可见图元" in notice for notice in preview.notices)


def test_long_multiline_frame_graphics_export_has_no_oversized_strings(tmp_path: Path) -> None:

    from mycad import app
    from mycad.core.geometric_tolerance import FeatureControlFrame, ToleranceRow

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    frame = FeatureControlFrame(
        "be" * 16, tuple(ToleranceRow("flatness", 0.1, 1) for _ in range(16)), (0, 0)
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    preview = prepare_dxf_output_preview(services.kernel, tolerance_graphics=True)
    path = tmp_path / "long-graphics.dxf"
    preview.write(path)
    document = _read_dxf(path)
    assert not document.modelspace().query("TOLERANCE")
    assert len(document.modelspace().query("LINE")) > 16
    assert all(
        len(entity.dxf.text.encode("utf-8")) <= 255
        for entity in document.modelspace().query("TEXT")
    )
    assert any("不可" in warning and "编辑" in warning for warning in preview.report.warnings)


def test_graphics_export_rejects_oversized_single_text_cell() -> None:
    from mycad import app
    from mycad.core.geometric_tolerance import DatumReference, FeatureControlFrame, ToleranceRow

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    row = ToleranceRow("position", 0.1, 1, datums=(DatumReference("𠀀" * 70),))
    frame = FeatureControlFrame("bf" * 16, (row,), (0, 0))
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    with pytest.raises(ValueError, match="255"):
        prepare_dxf_output_preview(services.kernel, tolerance_graphics=True)


def test_short_frame_leader_graphics_export_reimports_as_visible_geometry(tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.geometric_tolerance import FeatureControlFrame, ToleranceRow

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    frame = FeatureControlFrame(
        "ab" * 16,
        (ToleranceRow("position", 0.1, 2),),
        (1, 0),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, 0),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    preview = prepare_dxf_output_preview(services.kernel, tolerance_graphics=True)
    path = tmp_path / "short-graphics.dxf"
    preview.write(path)
    result = read_sketch_dxf(path)
    assert not result.tolerance_frames
    assert any(
        isinstance(entity, LineEntity)
        and entity.start_mm == pytest.approx((0, 0))
        and entity.end_mm == pytest.approx((1, 0))
        for entity in result.sketch.entities
    )
    assert any("箭头" in warning and "轮廓" in warning for warning in result.report.warnings)
    assert any("不可" in warning and "编辑" in warning for warning in preview.report.warnings)
