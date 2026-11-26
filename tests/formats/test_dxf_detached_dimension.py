# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""External native dimensions without MyCAD geometry references."""

import math
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import ezdxf.filemanagement as filemanagement
import pytest

from mycad.formats.providers.dxf_provider import read_sketch_dxf


def _render_two_line_as_defined(native: Any) -> None:
    dxf = native.dimension.dxf
    saved = (dxf.defpoint2, dxf.defpoint3, dxf.defpoint4, dxf.defpoint)
    dxf.defpoint2, dxf.defpoint3, dxf.defpoint4, dxf.defpoint = (
        saved[2],
        saved[3],
        saved[0],
        saved[1],
    )
    native.render()
    dxf.defpoint2, dxf.defpoint3, dxf.defpoint4, dxf.defpoint = saved


@pytest.mark.parametrize("kind", ("radius", "diameter"))
def test_external_radial_dimension_and_tolerance_roundtrip(tmp_path: Path, kind: str) -> None:
    from mycad.formats.providers.dxf_provider import write_sketches_dxf

    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 4
    factory = getattr(document.modelspace(), f"add_{kind}_dim")
    native = factory(
        center=(0, 0),
        radius=10,
        angle=30,
        override={"dimtol": 1, "dimtp": 0.1, "dimtm": 0.2},
    )
    native.render()
    source = tmp_path / "external-radial.dxf"
    document.saveas(source)
    imported = read_sketch_dxf(source)
    assert len(imported.detached_dimensions) == 1
    dimension = imported.detached_dimensions[0]
    assert dimension.kind == kind
    assert dimension.nominal == pytest.approx(10 if kind == "radius" else 20)
    assert dimension.tolerance.upper_deviation == 0.1
    assert dimension.tolerance.lower_deviation == -0.2
    target = tmp_path / "roundtrip-radial.dxf"
    write_sketches_dxf((), target, reference_dimensions=(dimension,))
    restored = read_sketch_dxf(target).detached_dimensions[0]
    assert restored.kind == kind and restored.dimension_id == dimension.dimension_id
    assert restored.nominal == pytest.approx(dimension.nominal)
    assert restored.first_mm == pytest.approx(dimension.first_mm)
    assert restored.second_mm == pytest.approx(dimension.second_mm)
    assert restored.location_mm == pytest.approx(dimension.location_mm)
    assert restored.tolerance == dimension.tolerance


def test_external_micron_dimension_preserves_scaled_display_precision(tmp_path: Path) -> None:
    from mycad.formats.providers.dxf_provider import write_sketches_dxf

    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 13
    document.modelspace().add_linear_dim(
        base=(0, 5),
        p1=(0, 0),
        p2=(10, 0),
        override={"dimtol": 1, "dimtp": 0.01, "dimtm": 0.02, "dimdec": 2, "dimtdec": 2},
    ).render()
    source = tmp_path / "micron-dimension.dxf"
    document.saveas(source)
    imported = read_sketch_dxf(source)
    dimension = imported.detached_dimensions[0]
    assert dimension.nominal == pytest.approx(0.01)
    assert dimension.precision == 5 and dimension.tolerance.precision == 5
    assert dimension.tolerance.upper_deviation == pytest.approx(1e-5)
    assert dimension.tolerance.lower_deviation == pytest.approx(-2e-5)
    target = tmp_path / "scaled-dimension.dxf"
    write_sketches_dxf((), target, reference_dimensions=(dimension,))
    assert read_sketch_dxf(target).detached_dimensions[0].tolerance == dimension.tolerance


def test_external_radius_in_inches_scales_geometry_and_tolerance(tmp_path: Path) -> None:
    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 1
    native = document.modelspace().add_radius_dim(
        center=(0, 0), radius=1, angle=0, override={"dimtol": 1, "dimtp": 0.01, "dimtm": 0.02}
    )
    native.render()
    path = tmp_path / "radius-inches.dxf"
    document.saveas(path)
    dimension = read_sketch_dxf(path).detached_dimensions[0]
    assert dimension.nominal == pytest.approx(25.4)
    assert dimension.second_mm == pytest.approx((25.4, 0))
    assert dimension.tolerance.upper_deviation == pytest.approx(0.254)
    assert dimension.tolerance.lower_deviation == pytest.approx(-0.508)


def test_ezdxf_official_angular_tolerance_sample(tmp_path: Path) -> None:
    from mycad.formats.providers.dxf_provider import write_sketches_dxf

    source = Path(__file__).parents[1] / "fixtures/dxf/ezdxf-angular-tolerance-r2013.dxf"
    imported = read_sketch_dxf(source, unit_override="mm")
    assert len(imported.detached_dimensions) == 16
    for index, dimension in enumerate(imported.detached_dimensions):
        assert dimension.kind == "angular_3p"
        assert dimension.nominal == pytest.approx((60, 300, 60, 90)[index % 4])
        assert dimension.tolerance.mode == ("none", "none", "deviation", "limits")[index % 4]
        factor = (1, 1, 0.9, 180 / math.pi)[index // 4]
        assert dimension.tolerance.upper_deviation == pytest.approx(factor)
        assert dimension.tolerance.lower_deviation == pytest.approx(-2 * factor)
    assert sum("未导入其语义" in warning for warning in imported.report.warnings) == 0
    assert sum("作为参考尺寸导入" in warning for warning in imported.report.warnings) == 16
    assert sum("角度显示单位" in warning for warning in imported.report.warnings) == 12
    metres = read_sketch_dxf(source)
    assert metres.detached_dimensions[2].vertex_mm == pytest.approx((20000, 0))
    assert metres.detached_dimensions[2].tolerance == imported.detached_dimensions[2].tolerance
    output = tmp_path / "angle-units-roundtrip.dxf"
    write_sketches_dxf((), output, reference_dimensions=imported.detached_dimensions)
    roundtrip = read_sketch_dxf(output)
    assert [item.tolerance for item in roundtrip.detached_dimensions] == [
        item.tolerance for item in imported.detached_dimensions
    ]


def test_unknown_angular_tolerance_unit_is_reported(tmp_path: Path) -> None:
    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 4
    native = document.modelspace().add_angular_dim_3p(
        base=(2, 2),
        center=(0, 0),
        p1=(4, 0),
        p2=(0, 4),
        override={"dimaunit": 4, "dimtol": 1, "dimtp": 0.1, "dimtm": 0.2},
    )
    native.commit()
    source = tmp_path / "angular-unknown-unit.dxf"
    document.saveas(source)
    imported = read_sketch_dxf(source)
    assert not imported.detached_dimensions
    assert any("角度公差单位代码 4 不受支持" in warning for warning in imported.report.warnings)


def test_external_three_point_angular_dimension_preserves_degree_tolerance(tmp_path: Path) -> None:
    from mycad.formats.providers.dxf_provider import write_sketches_dxf

    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 1
    native = document.modelspace().add_angular_dim_3p(
        base=(2, 2),
        center=(0, 0),
        p1=(4, 0),
        p2=(0, 4),
        override={"dimtol": 1, "dimtp": 0.1, "dimtm": 0.2},
    )
    native.render()
    source = tmp_path / "angular.dxf"
    document.saveas(source)
    dimension = read_sketch_dxf(source).detached_dimensions[0]
    assert dimension.kind == "angular_3p"
    assert dimension.nominal == pytest.approx(90)
    assert dimension.first_mm == pytest.approx((101.6, 0))
    assert dimension.vertex_mm == pytest.approx((0, 0))
    assert dimension.tolerance.upper_deviation == pytest.approx(0.1)
    assert dimension.tolerance.lower_deviation == pytest.approx(-0.2)
    target = tmp_path / "angular-roundtrip.dxf"
    write_sketches_dxf((), target, reference_dimensions=(dimension,))
    restored = read_sketch_dxf(target).detached_dimensions[0]
    assert restored.kind == "angular_3p"
    assert restored.nominal == pytest.approx(90)
    assert restored.vertex_mm == pytest.approx(dimension.vertex_mm)
    assert restored.tolerance == dimension.tolerance


def test_external_reflex_angle_and_tolerance_roundtrip(tmp_path: Path) -> None:
    from mycad.formats.providers.dxf_provider import write_sketches_dxf

    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 4
    document.modelspace().add_angular_dim_3p(
        base=(-20, -20),
        center=(0, 0),
        p1=(0, 30),
        p2=(30, 0),
        override={"dimtol": 1, "dimtp": 0.1, "dimtm": 0.2},
    ).render()
    path = tmp_path / "reflex-angle.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    dimension = imported.detached_dimensions[0]
    assert dimension.nominal == pytest.approx(270)
    assert dimension.tolerance.upper_deviation == pytest.approx(0.1)
    assert dimension.tolerance.lower_deviation == pytest.approx(-0.2)
    output = tmp_path / "reflex-roundtrip.dxf"
    write_sketches_dxf((), output, reference_dimensions=(dimension,))
    exported = (
        cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(output)
        .modelspace()
        .query("DIMENSION")[0]
    )
    spans: list[float] = [
        float((arc.dxf.end_angle - arc.dxf.start_angle) % 360)
        for arc in exported.virtual_entities()
        if arc.dxftype() == "ARC"
    ]
    assert sum(spans) > 180
    restored = read_sketch_dxf(output).detached_dimensions[0]
    assert restored.nominal == pytest.approx(270)
    assert restored.tolerance == dimension.tolerance


def test_hidden_reference_tolerance_does_not_overwrite_export(tmp_path: Path) -> None:
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.dimension_tolerance import DimensionTolerance
    from mycad.core.exceptions import ValidationError
    from mycad.formats.providers.dxf_provider import write_sketches_dxf

    dimension = DetachedDimension(
        uuid4().hex,
        "rotated",
        (0, 0),
        (20, 0),
        (0, 5),
        0,
        20,
        DimensionTolerance("symmetric", 1e-10, -1e-10, 8),
    )
    target = tmp_path / "tiny-reference.dxf"
    target.write_bytes(b"existing drawing")
    with pytest.raises(ValidationError, match="精度"):
        write_sketches_dxf((), target, reference_dimensions=(dimension,))
    assert target.read_bytes() == b"existing drawing"


def test_import_warns_when_tiny_angular_tolerance_displays_as_zero(tmp_path: Path) -> None:
    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 4
    native = document.modelspace().add_angular_dim_3p(
        base=(2, 2),
        center=(0, 0),
        p1=(4, 0),
        p2=(0, 4),
        override={"dimaunit": 3, "dimtol": 1, "dimtp": 1e-12, "dimtm": 1e-12, "dimtdec": 8},
    )
    native.render()
    source = tmp_path / "tiny-angular.dxf"
    document.saveas(source)
    imported = read_sketch_dxf(source)
    dimension = imported.detached_dimensions[0]
    assert dimension.tolerance.upper_deviation == pytest.approx(math.degrees(1e-12))
    assert any(
        "非零公差" in warning and "显示为零" in warning for warning in imported.report.warnings
    )


def test_external_two_line_grad_tolerance_keeps_display_precision(tmp_path: Path) -> None:
    from mycad.formats.providers.dxf_provider import write_sketches_dxf

    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 4
    style = document.dimstyles.get("Standard")
    style.dxf.dimaunit = 2
    style.dxf.dimtol = 1
    style.dxf.dimtp = 0.05
    style.dxf.dimtm = 0.05
    style.dxf.dimtdec = 2
    native = document.modelspace().add_angular_dim_2l(
        base=(4, 4), line1=((-5, 0), (5, 0)), line2=((0, -5), (0, 5))
    )
    _render_two_line_as_defined(native)
    source = tmp_path / "angular-grad.dxf"
    document.saveas(source)
    imported = read_sketch_dxf(source)
    dimension = imported.detached_dimensions[0]
    assert dimension.kind == "angular_2l"
    assert dimension.tolerance.upper_deviation == pytest.approx(0.045)
    assert dimension.tolerance.lower_deviation == pytest.approx(-0.045)
    assert dimension.tolerance.precision >= 3
    assert dimension.precision >= 3
    assert any("百分度" in message for message in imported.report.warnings)
    target = tmp_path / "angular-grad-roundtrip.dxf"
    write_sketches_dxf((), target, reference_dimensions=(dimension,))
    restored = read_sketch_dxf(target).detached_dimensions[0]
    assert restored.tolerance == dimension.tolerance


def test_external_two_line_angle_tolerance_roundtrip(tmp_path: Path) -> None:
    from mycad.formats.providers.dxf_provider import write_sketches_dxf

    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 4
    native = document.modelspace().add_angular_dim_2l(
        base=(4, 4),
        line1=((-5, 0), (5, 0)),
        line2=((0, -5), (0, 5)),
        override={"dimtol": 1, "dimtp": 0.1, "dimtm": 0.2},
    )
    _render_two_line_as_defined(native)
    source = tmp_path / "two-lines.dxf"
    document.saveas(source)
    imported = read_sketch_dxf(source)
    assert len(imported.detached_dimensions) == 1
    dimension = imported.detached_dimensions[0]
    assert dimension.kind == "angular_2l" and dimension.vertex_mm == pytest.approx((0, 0))
    assert any("原始线端位置不保留" in warning for warning in imported.report.warnings)
    assert dimension.nominal == pytest.approx(90)
    assert dimension.tolerance.upper_deviation == pytest.approx(0.1)
    assert dimension.tolerance.lower_deviation == pytest.approx(-0.2)
    target = tmp_path / "two-lines-roundtrip.dxf"
    write_sketches_dxf((), target, reference_dimensions=(dimension,))
    restored = read_sketch_dxf(target).detached_dimensions[0]
    assert restored.kind == dimension.kind
    assert restored.nominal == pytest.approx(dimension.nominal)
    assert restored.vertex_mm == pytest.approx(dimension.vertex_mm)
    assert restored.tolerance == dimension.tolerance


@pytest.mark.parametrize("mode", ["none", "deviation", "limits"])
def test_exported_two_line_angle_graphics_match_measurement(tmp_path: Path, mode: str) -> None:
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.dimension_tolerance import DimensionTolerance
    from mycad.formats.providers.dxf_provider import write_sketches_dxf

    dimension = DetachedDimension(
        uuid4().hex,
        "angular_2l",
        (30, 0),
        (0, 30),
        (20, 20),
        0,
        90,
        DimensionTolerance(mode, 0.1, -0.2),
        vertex_mm=(0, 0),
    )
    path = tmp_path / "two-line-graphics.dxf"
    write_sketches_dxf((), path, reference_dimensions=(dimension,))
    native = (
        cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
        .modelspace()
        .query("DIMENSION")[0]
    )
    assert native.get_measurement() == pytest.approx(90)
    texts: list[str] = [
        str(item.dxf.text) for item in native.virtual_entities() if item.dxftype() == "MTEXT"
    ]
    assert any("90" in text for text in texts)
    assert all("270" not in text for text in texts)
    spans: list[float] = [
        float((arc.dxf.end_angle - arc.dxf.start_angle) % 360)
        for arc in native.virtual_entities()
        if arc.dxftype() == "ARC"
    ]
    assert 40 < sum(spans) < 90


def test_external_two_line_angle_with_conflicting_graphics_is_not_imported(
    tmp_path: Path,
) -> None:
    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 4
    dimension = document.modelspace().add_angular_dim_2l(
        base=(20, 20), line1=((0, 0), (30, 0)), line2=((0, 0), (0, 30))
    )
    dimension.render()
    path = tmp_path / "conflicting-two-line.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert not imported.detached_dimensions
    assert any("图形与角度定义不一致" in warning for warning in imported.report.warnings)


@pytest.mark.parametrize("mode", ["none", "deviation", "limits"])
def test_two_line_reflex_angle_graphics_and_roundtrip(tmp_path: Path, mode: str) -> None:
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.dimension_tolerance import DimensionTolerance
    from mycad.formats.providers.dxf_provider import write_sketches_dxf

    dimension = DetachedDimension(
        uuid4().hex,
        "angular_2l",
        (0, 30),
        (30, 0),
        (-20, -20),
        0,
        270,
        DimensionTolerance(mode, 0.1, -0.2),
        vertex_mm=(0, 0),
    )
    path = tmp_path / "two-line-reflex.dxf"
    write_sketches_dxf((), path, reference_dimensions=(dimension,))
    native = (
        cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
        .modelspace()
        .query("DIMENSION")[0]
    )
    assert native.get_measurement() == pytest.approx(270)
    texts: list[str] = [
        str(item.dxf.text) for item in native.virtual_entities() if item.dxftype() == "MTEXT"
    ]
    assert any("270" in text for text in texts)
    spans: list[float] = [
        float((arc.dxf.end_angle - arc.dxf.start_angle) % 360)
        for arc in native.virtual_entities()
        if arc.dxftype() == "ARC"
    ]
    assert sum(spans) > 180
    imported = read_sketch_dxf(path)
    restored = imported.detached_dimensions[0]
    assert restored.kind == "angular_2l" and restored.nominal == pytest.approx(270)
    assert restored.tolerance == dimension.tolerance


def test_external_two_line_reflex_without_metadata(tmp_path: Path) -> None:
    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 4
    native = document.modelspace().add_angular_dim_2l(
        base=(-20, -20),
        line1=((0, 0), (0, 30)),
        line2=((0, 0), (30, 0)),
        override={"dimtol": 1, "dimtp": 0.1, "dimtm": 0.2},
    )
    _render_two_line_as_defined(native)
    path = tmp_path / "external-two-line-reflex.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    dimension = imported.detached_dimensions[0]
    assert dimension.kind == "angular_2l" and dimension.nominal == pytest.approx(270)
    assert dimension.tolerance.upper_deviation == pytest.approx(0.1)
    assert dimension.tolerance.lower_deviation == pytest.approx(-0.2)


def test_cadcraft_resaved_two_line_reflex_preserves_angle_and_tolerance() -> None:
    path = Path(__file__).parents[1] / "fixtures/dxf/cadcraft-two-line-reflex-resaved.dxf"
    imported = read_sketch_dxf(path)
    assert len(imported.detached_dimensions) == 1
    dimension = imported.detached_dimensions[0]
    assert dimension.dimension_id == "45" * 16
    assert dimension.kind == "angular_2l" and dimension.nominal == pytest.approx(270)
    assert dimension.tolerance.mode == "deviation"
    assert dimension.tolerance.upper_deviation == pytest.approx(0.1)
    assert dimension.tolerance.lower_deviation == pytest.approx(-0.2)
    assert not any("未导入其语义" in warning for warning in imported.report.warnings)
    assert not any("尺寸图形未显示公差" in warning for warning in imported.report.warnings)


def test_cadcraft_edited_reflex_reports_graphic_missing_tolerance() -> None:
    path = Path(__file__).parents[1] / "fixtures/dxf/cadcraft-two-line-reflex-edited.dxf"
    imported = read_sketch_dxf(path)
    assert len(imported.detached_dimensions) == 1
    dimension = imported.detached_dimensions[0]
    assert dimension.dimension_id == "45" * 16
    assert dimension.nominal == pytest.approx(270)
    assert dimension.tolerance.upper_deviation == pytest.approx(0.3)
    assert dimension.tolerance.lower_deviation == pytest.approx(-0.4)
    assert any("尺寸图形未显示公差" in warning for warning in imported.report.warnings)
    assert any("角度弧线不可核对" in warning for warning in imported.report.warnings)


@pytest.mark.parametrize("kind", ["angular_3p", "angular_2l"])
@pytest.mark.parametrize("graphic", ["missing", "empty", "points"])
def test_angular_tolerance_without_graphic_block_keeps_structured_data(
    tmp_path: Path, kind: str, graphic: str
) -> None:
    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 4
    space = document.modelspace()
    override = {"dimtol": 1, "dimtp": 0.1, "dimtm": 0.2}
    if kind == "angular_3p":
        native = space.add_angular_dim_3p(
            base=(4, 4), center=(0, 0), p1=(10, 0), p2=(0, 10), override=override
        )
    else:
        native = space.add_angular_dim_2l(
            base=(4, 4), line1=((0, 0), (10, 0)), line2=((0, 0), (0, 10)), override=override
        )
    native.commit()
    if graphic in ("empty", "points"):
        block = document.blocks.new_anonymous_block("D")
        if graphic == "points":
            block.add_point((0, 0))
        native.dimension.dxf.geometry = block.name
        native.dimension.dxf.text_midpoint = (0, 0, 0)
    path = tmp_path / "no-graphic.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert len(imported.detached_dimensions) == 1
    dimension = imported.detached_dimensions[0]
    assert dimension.kind == kind and dimension.nominal == pytest.approx(90)
    assert dimension.tolerance.upper_deviation == pytest.approx(0.1)
    assert dimension.tolerance.lower_deviation == pytest.approx(-0.2)
    assert any("尺寸图形不可核对" in warning for warning in imported.report.warnings)
    assert not any("未导入其语义" in warning for warning in imported.report.warnings)


@pytest.mark.parametrize("side", [1, -1])
def test_external_three_point_straight_angle_preserves_semicircle(
    tmp_path: Path, side: int
) -> None:
    from mycad.formats.providers.dxf_provider import write_sketches_dxf

    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 4
    native = document.modelspace().add_angular_dim_3p(
        base=(0, side * 15),
        center=(0, 0),
        p1=(10, 0),
        p2=(-10, 0),
        override={"dimtol": 1, "dimtp": 0.1, "dimtm": 0.2},
    )
    native.commit()
    source = tmp_path / "straight-source.dxf"
    document.saveas(source)
    imported = read_sketch_dxf(source)
    dimension = imported.detached_dimensions[0]
    assert dimension.nominal == pytest.approx(180)
    assert dimension.first_mm[0] == side * 10
    assert dimension.tolerance.upper_deviation == pytest.approx(0.1)
    assert dimension.tolerance.lower_deviation == pytest.approx(-0.2)
    output = tmp_path / "straight-out.dxf"
    write_sketches_dxf((), output, reference_dimensions=(dimension,))
    result = read_sketch_dxf(output).detached_dimensions[0]
    assert result.first_mm == pytest.approx(dimension.first_mm)
    exported = (
        cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(output)
        .modelspace()
        .query("DIMENSION")[0]
    )
    arcs: list[Any] = [item for item in exported.virtual_entities() if item.dxftype() == "ARC"]
    assert arcs
    for arc in arcs:
        mid = math.radians(
            float(arc.dxf.start_angle)
            + ((float(arc.dxf.end_angle) - float(arc.dxf.start_angle)) % 360) / 2
        )
        assert side * math.sin(mid) > 0


def test_external_straight_angle_conflicting_semicircle_is_reported(tmp_path: Path) -> None:
    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 4
    native = document.modelspace().add_angular_dim_3p(
        base=(0, -15), center=(0, 0), p1=(10, 0), p2=(-10, 0)
    )
    native.render()
    path = tmp_path / "conflicting-straight-angle.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert not imported.detached_dimensions
    assert any("图形与角度定义不一致" in warning for warning in imported.report.warnings)


@pytest.mark.parametrize("nominal", [90, 270])
def test_external_three_point_angle_with_opposite_arc_is_rejected(
    tmp_path: Path, nominal: int
) -> None:
    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 4
    first, second = ((30, 0), (0, 30)) if nominal == 90 else ((0, 30), (30, 0))
    native = document.modelspace().add_angular_dim_3p(
        base=(-20, -20) if nominal == 270 else (20, 20),
        center=(0, 0),
        p1=first,
        p2=second,
        override={"dimtol": 1, "dimtp": 0.1, "dimtm": 0.2},
    )
    native.render()
    for arc in native.dimension.get_geometry_block().query("ARC"):
        arc.dxf.start_angle, arc.dxf.end_angle = (200, 220) if nominal == 90 else (10, 30)
    path = tmp_path / "wrong-arc.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert not imported.detached_dimensions
    assert any("图形与角度定义不一致" in warning for warning in imported.report.warnings)


def test_cadcraft_resaved_straight_angle_preserves_semicircle_and_tolerance() -> None:
    path = Path(__file__).parents[1] / "fixtures/dxf/cadcraft-straight-angle-resaved.dxf"
    imported = read_sketch_dxf(path)
    assert len(imported.detached_dimensions) == 1
    dimension = imported.detached_dimensions[0]
    assert dimension.dimension_id == "46" * 16
    assert dimension.nominal == pytest.approx(180)
    assert dimension.first_mm == pytest.approx((-10, 0))
    assert dimension.location_mm == pytest.approx((0, -15))
    assert dimension.tolerance.upper_deviation == pytest.approx(0.1)
    assert dimension.tolerance.lower_deviation == pytest.approx(-0.2)
    assert not any("未导入其语义" in warning for warning in imported.report.warnings)


def test_cadcraft_edited_straight_angle_preserves_data_and_warns_about_graphics() -> None:
    path = Path(__file__).parents[1] / "fixtures/dxf/cadcraft-straight-angle-edited.dxf"
    imported = read_sketch_dxf(path)
    assert len(imported.detached_dimensions) == 1
    dimension = imported.detached_dimensions[0]
    assert dimension.dimension_id == "46" * 16
    assert dimension.nominal == pytest.approx(180)
    assert dimension.first_mm == pytest.approx((-10, 0))
    assert dimension.location_mm == pytest.approx((0, -15))
    assert dimension.tolerance.upper_deviation == pytest.approx(0.3)
    assert dimension.tolerance.lower_deviation == pytest.approx(-0.4)
    assert any("尺寸图形未显示公差" in warning for warning in imported.report.warnings)
    assert any("角度弧线不可核对" in warning for warning in imported.report.warnings)


@pytest.mark.parametrize(
    ("sample", "nominal", "first", "location"),
    [
        ("cadcraft-independent-reflex.dxf", 270, (0, 30), (-20, -20)),
        ("cadcraft-independent-straight.dxf", 180, (-10, 0), (0, -15)),
    ],
)
def test_cadcraft_independent_angle_import(
    sample: str, nominal: int, first: tuple[int, int], location: tuple[int, int]
) -> None:
    path = Path(__file__).parents[1] / "fixtures/dxf" / sample
    imported = read_sketch_dxf(path)
    assert len(imported.detached_dimensions) == 1
    dimension = imported.detached_dimensions[0]
    assert dimension.kind == "angular_3p"
    assert dimension.nominal == pytest.approx(nominal)
    assert dimension.first_mm == pytest.approx(first)
    assert dimension.location_mm == pytest.approx(location)
    assert dimension.tolerance.mode == "deviation"
    assert dimension.tolerance.upper_deviation == pytest.approx(0.1)
    assert dimension.tolerance.lower_deviation == pytest.approx(-0.2)
    assert any("尺寸图形未显示公差" in warning for warning in imported.report.warnings)
    assert any("角度弧线不可核对" in warning for warning in imported.report.warnings)
    assert not any("未导入其语义" in warning for warning in imported.report.warnings)


@pytest.mark.parametrize(
    "sample", ["cadcraft-straight-angle-edited.dxf", "cadcraft-two-line-reflex-edited.dxf"]
)
def test_discretized_angle_with_wrong_side_is_rejected(tmp_path: Path, sample: str) -> None:
    source = Path(__file__).parents[1] / "fixtures/dxf" / sample
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(source)
    dimension = document.modelspace().query("DIMENSION")[0]
    for line in dimension.get_geometry_block().query("LINE"):
        line.dxf.start = line.dxf.start.replace(y=-line.dxf.start.y)
        line.dxf.end = line.dxf.end.replace(y=-line.dxf.end.y)
    path = tmp_path / "opposite-polyline-angle.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert not imported.detached_dimensions
    assert any("图形与角度定义不一致" in warning for warning in imported.report.warnings)


def test_isolated_line_near_dimension_circle_does_not_prove_wrong_side(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "fixtures/dxf/cadcraft-straight-angle-edited.dxf"
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(source)
    dimension = document.modelspace().query("DIMENSION")[0]
    block = dimension.get_geometry_block()
    for line in list(block.query("LINE")):
        block.delete_entity(line)
    angle1, angle2 = math.radians(45), math.radians(50)
    block.add_line(
        (15 * math.cos(angle1), 15 * math.sin(angle1)),
        (15 * math.cos(angle2), 15 * math.sin(angle2)),
    )
    path = tmp_path / "isolated-line.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert len(imported.detached_dimensions) == 1
    assert any("角度弧线不可核对" in warning for warning in imported.report.warnings)


@pytest.mark.parametrize("factor", [0.7, 1.0, 2.0])
def test_angular_tolerance_dxf_arc_does_not_cross_text_bounds(
    tmp_path: Path, factor: float
) -> None:
    from uuid import uuid4

    from ezdxf import bbox

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.dimension_tolerance import DimensionTolerance
    from mycad.formats.providers.dxf_provider import write_sketches_dxf

    dimension = DetachedDimension(
        uuid4().hex,
        "angular_2l",
        (0, 30),
        (30, 0),
        (-20, -20),
        0,
        270,
        DimensionTolerance("deviation", 0.1, -0.2, text_factor=factor),
        vertex_mm=(0, 0),
    )
    path = tmp_path / "angular-clearance.dxf"
    write_sketches_dxf((), path, reference_dimensions=(dimension,))
    native = (
        cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
        .modelspace()
        .query("DIMENSION")[0]
    )
    graphics: list[Any] = list(native.virtual_entities())
    label = next(item for item in graphics if item.dxftype() == "MTEXT")
    proxy = label.copy()
    proxy.text = "270,00°+0,10°\\P-0,20°"
    bounds = bbox.extents([proxy])
    total_span = 0.0
    for arc in (item for item in graphics if item.dxftype() == "ARC"):
        start = float(arc.dxf.start_angle)
        span = (float(arc.dxf.end_angle) - start) % 360
        total_span += span
        for index in range(501):
            angle = math.radians(start + span * index / 500)
            x = float(arc.dxf.center.x) + float(arc.dxf.radius) * math.cos(angle)
            y = float(arc.dxf.center.y) + float(arc.dxf.radius) * math.sin(angle)
            assert not (
                bounds.extmin.x < x < bounds.extmax.x and bounds.extmin.y < y < bounds.extmax.y
            )
    if factor == 1.0:
        assert total_span > 243


@pytest.mark.parametrize("axis", ("x", "y"))
def test_external_negative_ordinate_preserves_sign_and_units(tmp_path: Path, axis: str) -> None:
    from mycad.formats.providers.dxf_provider import write_sketches_dxf

    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 1
    native = document.modelspace().add_ordinate_dim(
        feature_location=(-2, -3),
        origin=(0, 0),
        offset=(1, 1),
        dtype=1 if axis == "x" else 0,
        override={"dimtol": 1, "dimtp": 0.01, "dimtm": 0.02},
    )
    native.render()
    source = tmp_path / "ordinate-inches.dxf"
    document.saveas(source)
    dimension = read_sketch_dxf(source).detached_dimensions[0]
    assert dimension.kind == f"ordinate_{axis}"
    assert dimension.nominal == pytest.approx(-50.8 if axis == "x" else -76.2)
    assert dimension.tolerance.upper_deviation == pytest.approx(0.254)
    assert dimension.tolerance.lower_deviation == pytest.approx(-0.508)
    target = tmp_path / "ordinate-roundtrip.dxf"
    write_sketches_dxf((), target, reference_dimensions=(dimension,))
    restored = read_sketch_dxf(target).detached_dimensions[0]
    assert restored.kind == dimension.kind
    assert restored.nominal == pytest.approx(dimension.nominal)
    assert restored.text_override == dimension.text_override
    assert restored.tolerance == dimension.tolerance


def test_external_linear_dimension_imports_as_detached_reference(tmp_path: Path) -> None:
    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 4
    document.modelspace().add_linear_dim(
        base=(0, 5),
        p1=(0, 0),
        p2=(10, 0),
        override={"dimtol": 1, "dimtp": 0.1, "dimtm": 0.2, "dimtdec": 2},
    ).render()
    path = tmp_path / "external.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert len(imported.detached_dimensions) == 1
    dimension = imported.detached_dimensions[0]
    assert dimension.kind == "rotated"
    assert dimension.nominal == 10
    assert dimension.first_mm == (0, 0) and dimension.second_mm == (10, 0)
    assert dimension.tolerance.mode == "deviation"
    assert dimension.tolerance.upper_deviation == 0.1
    assert dimension.tolerance.lower_deviation == -0.2
    assert not imported.sketch.constraints
    assert any("不关联几何" in warning for warning in imported.report.warnings)


def test_detached_dimension_writes_native_dimension_and_roundtrips(tmp_path: Path) -> None:
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.dimension_tolerance import DimensionTolerance
    from mycad.formats.providers.dxf_provider import write_sketches_dxf

    dimension = DetachedDimension(
        uuid4().hex,
        "rotated",
        (0, 0),
        (10, 0),
        (0, 5),
        0,
        10,
        DimensionTolerance("deviation", 0.1, -0.2),
    )
    path = tmp_path / "reference.dxf"
    report = write_sketches_dxf((), path, reference_dimensions=(dimension,))
    assert report.entity_count == 1
    imported = read_sketch_dxf(path).detached_dimensions[0]
    assert imported.dimension_id == dimension.dimension_id
    assert imported.kind == dimension.kind
    assert imported.nominal == dimension.nominal
    assert imported.tolerance == dimension.tolerance
    assert imported.first_mm == dimension.first_mm and imported.second_mm == dimension.second_mm


def test_aligned_dimension_and_inch_tolerances_convert_to_mm(tmp_path: Path) -> None:
    import pytest

    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 1
    native = document.modelspace().add_aligned_dim(
        p1=(0, 0), p2=(3, 4), distance=1, override={"dimtol": 1, "dimtp": 0.01, "dimtm": 0.01}
    )
    native.render()
    native.dimension.dxf.dimtype = 33
    path = tmp_path / "inches.dxf"
    document.saveas(path)
    dimension = read_sketch_dxf(path).detached_dimensions[0]
    assert dimension.kind == "aligned"
    assert dimension.nominal == pytest.approx(127)
    assert dimension.tolerance.upper_deviation == pytest.approx(0.254)
    assert dimension.tolerance.lower_deviation == pytest.approx(-0.254)
    assert dimension.second_mm == pytest.approx((76.2, 101.6))


def test_aligned_reference_export_preserves_native_dimension_kind(tmp_path: Path) -> None:
    from uuid import uuid4

    import pytest

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.formats.providers.dxf_provider import write_sketches_dxf

    dimension = DetachedDimension(uuid4().hex, "aligned", (0, 0), (3, 4), (2.2, 4.6), 0, 5)
    path = tmp_path / "aligned.dxf"
    write_sketches_dxf((), path, reference_dimensions=(dimension,))
    imported = read_sketch_dxf(path).detached_dimensions[0]
    assert imported.kind == "aligned"
    assert imported.nominal == pytest.approx(5)
    assert imported.location_mm == pytest.approx(dimension.location_mm)


def test_unsupported_external_dimension_text_placement_is_reported(tmp_path: Path) -> None:
    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 4
    native = document.modelspace().add_linear_dim(base=(0, 5), p1=(0, 0), p2=(10, 0))
    native.render()
    native.dimension.dxf.dimtype |= 128
    path = tmp_path / "manual-text.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert not imported.detached_dimensions
    assert any("文字位置" in warning for warning in imported.report.warnings)


def test_external_dimension_with_rich_text_is_reported_not_misrepresented(tmp_path: Path) -> None:
    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 4
    native = document.modelspace().add_linear_dim(
        base=(0, 5), p1=(0, 0), p2=(10, 0), text=r"<>\Xnote"
    )
    native.render()
    path = tmp_path / "rich.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert not imported.detached_dimensions
    assert any("文字格式" in warning for warning in imported.report.warnings)


def test_external_nonplanar_ordinate_is_reported(tmp_path: Path) -> None:
    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 4
    native = document.modelspace().add_ordinate_dim(
        feature_location=(5, 3), origin=(0, 0), offset=(1, 1), dtype=1
    )
    native.render()
    native.dimension.dxf.extrusion = (0, 1, 0)
    path = tmp_path / "rotated-ordinate.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert not imported.detached_dimensions
    assert any("未导入其语义" in warning for warning in imported.report.warnings)


@pytest.mark.parametrize("angle", [90.0, -45.0])
@pytest.mark.parametrize("axis", ["x", "y"])
def test_external_rotated_ordinate_retains_coordinates_and_tolerance(
    tmp_path: Path, angle: float, axis: str
) -> None:
    from mycad.formats.providers.dxf_provider import write_sketches_dxf

    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 4
    native = document.modelspace().add_ordinate_dim(
        feature_location=(6, 23),
        origin=(10, 20),
        offset=(4, 5),
        rotation=angle,
        dtype=1 if axis == "x" else 0,
        override={"dimtol": 1, "dimtp": 0.1, "dimtm": 0.2},
    )
    native.render()
    original = native.dimension
    expected_first = tuple(original.dxf.defpoint)[:2]
    expected_second = tuple(original.dxf.defpoint2)[:2]
    expected_location = tuple(original.dxf.defpoint3)[:2]
    source = tmp_path / "rotated.dxf"
    document.saveas(source)
    result = read_sketch_dxf(source)
    assert len(result.detached_dimensions) == 1
    dimension = result.detached_dimensions[0]
    assert dimension.angle_deg == pytest.approx(angle)
    assert dimension.first_mm == pytest.approx(expected_first)
    assert dimension.second_mm == pytest.approx(expected_second)
    assert dimension.location_mm == pytest.approx(expected_location)
    assert dimension.nominal == pytest.approx(-4 if axis == "x" else 3)
    assert dimension.tolerance.upper_deviation == pytest.approx(0.1)
    assert dimension.tolerance.lower_deviation == pytest.approx(-0.2)
    target = tmp_path / "rotated-roundtrip.dxf"
    write_sketches_dxf((), target, reference_dimensions=(dimension,))
    exported = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(target)
    entity = list(exported.modelspace().query("DIMENSION"))[0]
    assert entity.dxf.horizontal_direction == pytest.approx(-angle)
    texts = [item.text for item in entity.virtual_entities() if item.dxftype() == "MTEXT"]
    assert len(texts) == 1
    assert ("-4,00" if axis == "x" else "3,00") in texts[0]
    assert "+0,10" in texts[0] and "-0,20" in texts[0]
    restored = read_sketch_dxf(target).detached_dimensions[0]
    assert restored.angle_deg == pytest.approx(angle)
    assert restored.first_mm == pytest.approx(expected_first)
    assert restored.second_mm == pytest.approx(expected_second)
    assert restored.location_mm == pytest.approx(expected_location)
    assert restored.nominal == pytest.approx(dimension.nominal)
    assert restored.tolerance == dimension.tolerance


def test_external_removal_of_ordinate_axis_is_reported(tmp_path: Path) -> None:
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.formats.providers.dxf_provider import write_sketches_dxf

    dimension = DetachedDimension(uuid4().hex, "ordinate_y", (10, 20), (14, 23), (18, 28), 90, -4)
    path = tmp_path / "axis-removed.dxf"
    write_sketches_dxf((), path, reference_dimensions=(dimension,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    entity = list(document.modelspace().query("DIMENSION"))[0]
    entity.dxf.discard("horizontal_direction")
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert imported.detached_dimensions[0].nominal == pytest.approx(3)
    assert any("坐标轴" in warning and "改变" in warning for warning in imported.report.warnings)


@pytest.mark.parametrize("angle", [0, 90])
def test_external_ordinate_type_change_is_reported(tmp_path: Path, angle: int) -> None:
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.formats.providers.dxf_provider import write_sketches_dxf

    dimension = DetachedDimension(
        uuid4().hex,
        "ordinate_x",
        (0, 0),
        (4, 3),
        (8, 10),
        angle,
        4 if angle == 0 else 3,
    )
    target = tmp_path / "axis-type-changed.dxf"
    write_sketches_dxf((), target, reference_dimensions=(dimension,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(target)
    entity = list(document.modelspace().query("DIMENSION"))[0]
    entity.dxf.dimtype = int(entity.dxf.dimtype) & ~64
    document.saveas(target)
    imported = read_sketch_dxf(target)
    result = imported.detached_dimensions[0]
    assert result.kind == "ordinate_y"
    assert result.nominal == pytest.approx(3 if angle == 0 else -4)
    assert any("坐标轴" in warning and "改变" in warning for warning in imported.report.warnings)


@pytest.mark.parametrize("change", ["missing", "invalid", "duplicate"])
def test_ordinate_type_snapshot_backwards_compatibility_and_invalid_data(
    tmp_path: Path, change: str
) -> None:
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.formats.providers.dxf_provider import write_sketches_dxf

    dimension = DetachedDimension(uuid4().hex, "ordinate_x", (0, 0), (4, 3), (8, 10), 0, 4)
    target = tmp_path / "axis-type-snapshot.dxf"
    write_sketches_dxf((), target, reference_dimensions=(dimension,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(target)
    entity = list(document.modelspace().query("DIMENSION"))[0]
    appid = "MYCAD_REFERENCE_DIMENSION"
    values = [(tag.code, tag.value) for tag in entity.get_xdata(appid)]
    values = [tag for tag in values if not str(tag[1]).startswith("ORDINATE_TYPE_V1:")]
    if change == "invalid":
        values.append((1000, "ORDINATE_TYPE_V1:unknown"))
    elif change == "duplicate":
        values.extend(((1000, "ORDINATE_TYPE_V1:ordinate_x"),) * 2)
    entity.set_xdata(appid, values)
    document.saveas(target)
    imported = read_sketch_dxf(target)
    assert imported.detached_dimensions[0].nominal == pytest.approx(4)
    assert any("坐标轴类型快照无效" in warning for warning in imported.report.warnings) == (
        change != "missing"
    )


def test_rotated_ordinate_converts_inch_coordinates_and_tolerances(tmp_path: Path) -> None:
    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 1
    native = document.modelspace().add_ordinate_dim(
        feature_location=(2, 3),
        origin=(0, 0),
        offset=(1, 1),
        rotation=90,
        dtype=1,
        override={"dimtol": 1, "dimtp": 0.01, "dimtm": 0.02},
    )
    native.render()
    source = tmp_path / "rotated-inch.dxf"
    document.saveas(source)
    dimension = read_sketch_dxf(source).detached_dimensions[0]
    assert dimension.angle_deg == pytest.approx(90)
    assert dimension.nominal == pytest.approx(50.8)
    assert dimension.tolerance.upper_deviation == pytest.approx(0.254)
    assert dimension.tolerance.lower_deviation == pytest.approx(-0.508)


def test_cadcraft_resaved_rotated_ordinate_reports_axis_change() -> None:
    path = Path(__file__).parents[1] / "fixtures/dxf/cadcraft-rotated-ordinate-resaved.dxf"
    imported = read_sketch_dxf(path)
    dimension = imported.detached_dimensions[0]
    assert dimension.dimension_id == "e" * 32
    assert dimension.angle_deg == 0 and dimension.nominal == pytest.approx(3)
    assert dimension.tolerance.upper_deviation == pytest.approx(0.1)
    assert dimension.tolerance.lower_deviation == pytest.approx(-0.2)
    assert any("坐标轴" in warning and "改变" in warning for warning in imported.report.warnings)


@pytest.mark.parametrize("angle", [90.0, -45.0, 0.0, 360.0])
def test_rotated_ordinate_export_warns_of_axis_loss(tmp_path: Path, angle: float) -> None:
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.formats.providers.dxf_provider import write_sketches_dxf

    radians = math.radians(angle)
    nominal = 4 * math.cos(radians) + 3 * math.sin(radians)
    dimension = DetachedDimension(
        uuid4().hex, "ordinate_x", (0, 0), (4, 3), (8, 10), angle, nominal
    )
    report = write_sketches_dxf((), tmp_path / "ordinate.dxf", reference_dimensions=(dimension,))
    warned = any("坐标轴" in warning and "数值" in warning for warning in report.warnings)
    assert warned is (angle not in (0.0, 360.0))


@pytest.mark.parametrize("direction", [360.0, -360.0, 720.0])
@pytest.mark.parametrize("axis", ["x", "y"])
def test_external_full_turn_ordinate_preserves_dimension_and_tolerance(
    tmp_path: Path, direction: float, axis: str
) -> None:
    from mycad.formats.providers.dxf_provider import write_sketches_dxf

    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 4
    native = document.modelspace().add_ordinate_dim(
        feature_location=(-5, 3),
        origin=(0, 0),
        offset=(1, 1),
        dtype=1 if axis == "x" else 0,
        override={"dimtol": 1, "dimtp": 0.1, "dimtm": 0.2},
    )
    native.render()
    native.dimension.dxf.horizontal_direction = direction
    source = tmp_path / "full-turn.dxf"
    document.saveas(source)
    imported = read_sketch_dxf(source)
    assert len(imported.detached_dimensions) == 1
    dimension = imported.detached_dimensions[0]
    assert dimension.kind == f"ordinate_{axis}"
    assert dimension.nominal == pytest.approx(-5 if axis == "x" else 3)
    assert dimension.tolerance.upper_deviation == pytest.approx(0.1)
    assert dimension.tolerance.lower_deviation == pytest.approx(-0.2)
    target = tmp_path / "roundtrip.dxf"
    write_sketches_dxf((), target, reference_dimensions=(dimension,))
    restored = read_sketch_dxf(target).detached_dimensions[0]
    assert restored.nominal == pytest.approx(dimension.nominal)
    assert restored.tolerance == dimension.tolerance


@pytest.mark.parametrize("axis", ("x", "y"))
@pytest.mark.parametrize("rotation", (0, 90))
def test_negative_ordinate_limits_draw_signed_extremes(
    tmp_path: Path, axis: str, rotation: int
) -> None:
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.dimension_tolerance import DimensionTolerance
    from mycad.formats.providers.dxf_provider import write_sketches_dxf

    point = (
        ((-10, 0) if axis == "x" else (0, -10))
        if rotation == 0
        else ((0, -10) if axis == "x" else (10, 0))
    )
    dimension = DetachedDimension(
        uuid4().hex,
        f"ordinate_{axis}",
        (0, 0),
        point,
        (-12, 5),
        rotation,
        -10,
        DimensionTolerance("limits", 0.1, -0.2),
    )
    target = tmp_path / "limits.dxf"
    write_sketches_dxf((), target, reference_dimensions=(dimension,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(target)
    native = document.modelspace().query("DIMENSION")[0]
    labels = [
        item.dxf.text for item in document.blocks[native.dxf.geometry] if item.dxftype() == "MTEXT"
    ]
    assert len(labels) == 1
    assert "-9,90" in labels[0] and "-10,20" in labels[0]
    assert native.override().get("dimlim") == 1
    assert read_sketch_dxf(target).detached_dimensions[0].tolerance == dimension.tolerance


def test_overflowing_reference_limit_does_not_write_dxf(tmp_path: Path) -> None:
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.dimension_tolerance import DimensionTolerance
    from mycad.core.exceptions import ValidationError
    from mycad.formats.providers.dxf_provider import write_sketches_dxf

    dimension = DetachedDimension(
        uuid4().hex,
        "rotated",
        (0, 0),
        (1e308, 0),
        (0, 5),
        0,
        1e308,
        DimensionTolerance("limits", 1e308, 0),
    )
    target = tmp_path / "overflow-reference.dxf"
    target.write_bytes(b"existing drawing")
    with pytest.raises(ValidationError, match="极限"):
        write_sketches_dxf((), target, reference_dimensions=(dimension,))
    assert target.read_bytes() == b"existing drawing"


def test_reference_limits_rounding_does_not_export_negative_zero(tmp_path: Path) -> None:
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.dimension_tolerance import DimensionTolerance
    from mycad.formats.providers.dxf_provider import write_sketches_dxf

    dimension = DetachedDimension(
        uuid4().hex,
        "rotated",
        (0, 0),
        (0.01, 0),
        (0, 5),
        0,
        0.01,
        DimensionTolerance("limits", 0.01, -0.011, 2),
    )
    target = tmp_path / "reference-cross-zero.dxf"
    write_sketches_dxf((), target, reference_dimensions=(dimension,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(target)
    native = document.modelspace().query("DIMENSION")[0]
    label = next(
        item.dxf.text for item in document.blocks[native.dxf.geometry] if item.dxftype() == "MTEXT"
    )
    normalized = label.replace(",", ".")
    assert "0.02" in normalized and "0.00" in normalized and "-0.00" not in normalized
    assert read_sketch_dxf(target).detached_dimensions[0].tolerance == dimension.tolerance


def test_negative_ordinate_limits_may_cross_zero(tmp_path: Path) -> None:
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.dimension_tolerance import DimensionTolerance
    from mycad.formats.providers.dxf_provider import write_sketches_dxf

    dimension = DetachedDimension(
        uuid4().hex,
        "ordinate_x",
        (0, 0),
        (-0.05, 0),
        (-1, 2),
        0,
        -0.05,
        DimensionTolerance("limits", 0.1, -0.2),
    )
    target = tmp_path / "cross-zero.dxf"
    write_sketches_dxf((), target, reference_dimensions=(dimension,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(target)
    native = document.modelspace().query("DIMENSION")[0]
    labels = [
        item.dxf.text for item in document.blocks[native.dxf.geometry] if item.dxftype() == "MTEXT"
    ]
    assert len(labels) == 1
    assert "0,05" in labels[0] and "-0,25" in labels[0]


@pytest.mark.parametrize("kind", ("radius", "diameter", "ordinate_x"))
@pytest.mark.parametrize("custom", (False, True))
def test_reference_limits_graphics_retain_visible_text(
    tmp_path: Path, kind: str, custom: bool
) -> None:
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.dimension_tolerance import DimensionTolerance
    from mycad.formats.providers.dxf_provider import write_sketches_dxf

    point = (-10, 0) if kind == "ordinate_x" else (10, 0)
    nominal = -10 if kind == "ordinate_x" else 10
    dimension = DetachedDimension(
        uuid4().hex,
        kind,
        (0, 0),
        point,
        (-12, 5),
        0,
        nominal,
        DimensionTolerance("limits", 0.1, -0.2),
        text_override="A<>B" if custom else "",
    )
    path = tmp_path / "limits-text.dxf"
    write_sketches_dxf((), path, reference_dimensions=(dimension,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    native = document.modelspace().query("DIMENSION")[0]
    label = next(
        item.dxf.text for item in document.blocks[native.dxf.geometry] if item.dxftype() == "MTEXT"
    )
    prefix = "A" if custom else {"radius": "R", "diameter": "⌀", "ordinate_x": ""}[kind]
    suffix = "B" if custom else ("" if kind == "ordinate_x" else " mm")
    assert f"{prefix}{nominal + 0.1:.2f}{suffix}".replace(".", ",") in label
    assert f"{prefix}{nominal - 0.2:.2f}{suffix}".replace(".", ",") in label


@pytest.mark.parametrize("custom", (False, True))
def test_reference_angular_limits_show_correct_affixes(tmp_path: Path, custom: bool) -> None:
    from uuid import uuid4

    from ezdxf.tools.text import plain_mtext

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.dimension_tolerance import DimensionTolerance
    from mycad.formats.providers.dxf_provider import write_sketches_dxf

    dimension = DetachedDimension(
        uuid4().hex,
        "angular_3p",
        (10, 0),
        (0, 10),
        (5, 5),
        0,
        90,
        DimensionTolerance("limits", 0.1, -0.2),
        text_override="A<>B" if custom else "",
        vertex_mm=(0, 0),
    )
    path = tmp_path / "angle-limits.dxf"
    write_sketches_dxf((), path, reference_dimensions=(dimension,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    native = document.modelspace().query("DIMENSION")[0]
    label = next(
        item.dxf.text for item in document.blocks[native.dxf.geometry] if item.dxftype() == "MTEXT"
    )
    assert plain_mtext(label) == ("A90,10B\nA89,80B" if custom else "90,10°\n89,80°")


@pytest.mark.parametrize("kind", ("radius", "diameter", "angular_3p"))
def test_reference_custom_deviation_uses_exact_template(tmp_path: Path, kind: str) -> None:
    from uuid import uuid4

    from ezdxf.tools.text import plain_mtext

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.dimension_tolerance import DimensionTolerance
    from mycad.formats.providers.dxf_provider import write_sketches_dxf

    angular = kind == "angular_3p"
    dimension = DetachedDimension(
        uuid4().hex,
        kind,
        (10, 0) if angular else (0, 0),
        (0, 10) if angular else (10, 0),
        (5, 5),
        0,
        90 if angular else 10,
        DimensionTolerance("symmetric", 0.1, -0.1),
        text_override="A<>B",
        vertex_mm=(0, 0) if angular else None,
    )
    path = tmp_path / "custom-reference-deviation.dxf"
    write_sketches_dxf((), path, reference_dimensions=(dimension,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    native = document.modelspace().query("DIMENSION")[0]
    label = next(
        item.dxf.text for item in document.blocks[native.dxf.geometry] if item.dxftype() == "MTEXT"
    )
    assert ("A90,00B" if angular else "A10,00B") in plain_mtext(label)


@pytest.mark.parametrize("kind", ("radius", "diameter", "angular_3p", "ordinate_x"))
def test_reference_default_deviation_matches_canvas_units(tmp_path: Path, kind: str) -> None:
    from uuid import uuid4

    from ezdxf.tools.text import plain_mtext

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.dimension_tolerance import DimensionTolerance
    from mycad.formats.providers.dxf_provider import write_sketches_dxf

    angular = kind == "angular_3p"
    second = (0, 10) if angular else (-10, 0) if kind == "ordinate_x" else (10, 0)
    value = 90 if angular else -10 if kind == "ordinate_x" else 10
    dimension = DetachedDimension(
        uuid4().hex,
        kind,
        (10, 0) if angular else (0, 0),
        second,
        (5, 5),
        0,
        value,
        DimensionTolerance("symmetric", 0.1, -0.1),
        vertex_mm=(0, 0) if angular else None,
    )
    path = tmp_path / "default-reference-deviation.dxf"
    write_sketches_dxf((), path, reference_dimensions=(dimension,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    native = document.modelspace().query("DIMENSION")[0]
    label = next(
        item.dxf.text for item in document.blocks[native.dxf.geometry] if item.dxftype() == "MTEXT"
    )
    expected = {
        "radius": "R10,00 mm",
        "diameter": "⌀10,00 mm",
        "angular_3p": "90,00°",
        "ordinate_x": "-10,00",
    }[kind]
    assert expected in plain_mtext(label)
