# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""DXF dimensions expose native tolerance values."""

import math
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

import ezdxf.filemanagement as filemanagement
import pytest

from mycad.core.dimension_tolerance import DimensionTolerance
from mycad.core.sketch import ArcEntity, CircleEntity, LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketches_dxf


@pytest.mark.parametrize(
    "prefix,warning_expected", [("A" * 253, False), ("A" * 254, True), ("字" * 85, True)]
)
def test_long_native_dimension_text_reports_portability_risk(
    tmp_path: Path, prefix: str, warning_expected: bool
) -> None:
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        text_override=prefix + "<>",
        tolerance=DimensionTolerance("deviation", 0.02, -0.01),
    )
    path = tmp_path / "long-dimension.dxf"
    report = write_sketches_dxf(
        (Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)),), path
    )
    assert (
        any("尺寸文字" in warning and "255" in warning for warning in report.warnings)
        == warning_expected
    )
    assert read_sketch_dxf(path).sketch.constraints == (dimension,)


def test_long_detached_dimension_text_reports_portability_risk(tmp_path: Path) -> None:
    from mycad.core.detached_dimension import DetachedDimension

    dimension = DetachedDimension(
        uuid4().hex,
        "aligned",
        (0, 0),
        (20, 0),
        (10, 5),
        0,
        20,
        tolerance=DimensionTolerance("deviation", 0.02, -0.01),
        text_override="字" * 85 + "<>",
    )
    path = tmp_path / "long-detached.dxf"
    report = write_sketches_dxf((), path, reference_dimensions=(dimension,))
    assert any("尺寸文字" in warning and "255" in warning for warning in report.warnings)
    assert read_sketch_dxf(path).detached_dimensions == (dimension,)


def test_cadcraft_edited_angular_tolerance_converts_radians_and_keeps_references() -> None:
    path = Path(__file__).parents[1] / "fixtures/dxf/cadcraft-angle-edited.dxf"
    result = read_sketch_dxf(path)
    assert len(result.sketch.constraints) == 1
    dimension = result.sketch.constraints[0]
    assert dimension.constraint_id == "33" * 16
    assert tuple(ref.entity_id for ref in dimension.references) == ("11" * 16, "22" * 16)
    assert dimension.tolerance is not None
    assert dimension.tolerance.upper_deviation == pytest.approx(math.degrees(0.01))
    assert dimension.tolerance.lower_deviation == pytest.approx(math.degrees(-0.02))
    assert dimension.tolerance.precision == 8
    assert any("角度显示单位不保留" in warning for warning in result.report.warnings)
    assert not any("部分修改未恢复" in warning for warning in result.report.warnings)


def test_cadcraft_edited_associated_angle_warns_graphic_omits_tolerance() -> None:
    path = Path(__file__).parents[1] / "fixtures/dxf/cadcraft-angle-edited.dxf"
    result = read_sketch_dxf(path)
    assert len(result.sketch.constraints) == 1
    assert any("尺寸图形未显示公差" in warning for warning in result.report.warnings)


def test_missing_angular_group_16_does_not_change_nonzero_vertex(tmp_path: Path) -> None:
    first = LineEntity(uuid4().hex, (100, 50), (120, 50))
    second = LineEntity(uuid4().hex, (100, 50), (100, 70))
    dimension = SketchConstraint(
        uuid4().hex,
        "angle",
        (
            SketchGeometryReference(first.entity_id, "geometry"),
            SketchGeometryReference(second.entity_id, "geometry"),
        ),
        90,
        "deg",
        driving=False,
    )
    path = tmp_path / "offset-angle.dxf"
    write_sketches_dxf(
        (Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second), (dimension,)),), path
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    native = document.modelspace().query("DIMENSION")[0]
    assert tuple(native.dxf.defpoint4) == (100, 50, 0)
    native.dxf.discard("defpoint5")
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert result.sketch.constraints == (dimension,)
    assert not any("部分修改未恢复" in warning for warning in result.report.warnings)


def test_nonzero_angular_group_16_change_is_still_reported(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "fixtures/dxf/cadcraft-angle-edited.dxf"
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(source)
    dimension = document.modelspace().query("DIMENSION")[0]
    dimension.dxf.defpoint5 = (4, 5, 0)
    path = tmp_path / "changed-group-16.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert any("部分修改未恢复" in warning for warning in imported.report.warnings)


def test_cadcraft_edited_mycad_dimension_uses_external_tolerance() -> None:
    path = Path(__file__).parents[1] / "fixtures/dxf/cadcraft-dimension-edited.dxf"
    result = read_sketch_dxf(path)
    assert len(result.sketch.constraints) == 1
    dimension = result.sketch.constraints[0]
    assert dimension.constraint_id == "02" * 16
    assert dimension.references[0].entity_id == "01" * 16
    assert dimension.tolerance is not None
    assert dimension.tolerance.upper_deviation == 0.04
    assert dimension.tolerance.lower_deviation == 0.01
    assert dimension.text_position_mm is None
    assert any("外部公差" in warning for warning in result.report.warnings)
    assert not any("部分修改未恢复" in warning for warning in result.report.warnings)


def test_nonempty_external_dimension_suffix_is_still_reported(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "fixtures/dxf/cadcraft-dimension-edited.dxf"
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(source)
    dimension = document.modelspace().query("DIMENSION")[0]
    style = dimension.override()
    style["dimpost"] = "<> custom"
    style.commit()
    path = tmp_path / "suffix.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert any("部分修改未恢复" in warning for warning in imported.report.warnings)


def test_cadcraft_created_dimension_imports_as_reference() -> None:
    path = Path(__file__).parents[1] / "fixtures/dxf/cadcraft-dimension-created.dxf"
    result = read_sketch_dxf(path, unit_override="mm")
    assert len(result.detached_dimensions) == 1
    dimension = result.detached_dimensions[0]
    assert dimension.nominal == 20
    assert dimension.tolerance.upper_deviation == 0.02
    assert dimension.tolerance.lower_deviation == -0.01
    assert any("参考尺寸" in warning for warning in result.report.warnings)


@pytest.mark.parametrize("manual_before", [False, True])
def test_external_dimension_text_position_flag_change_is_respected(
    tmp_path: Path, manual_before: bool
) -> None:
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        text_position_mm=(10, 8) if manual_before else None,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    path = tmp_path / "position-flag.dxf"
    write_sketches_dxf((sketch,), path)
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    native = document.modelspace().query("DIMENSION")[0]
    assert bool(native.dxf.dimtype & 128) == manual_before
    expected = tuple(native.dxf.text_midpoint)[:2]
    native.dxf.dimtype ^= 128
    document.saveas(path)
    restored = read_sketch_dxf(path).sketch.constraints[0]
    assert restored.text_position_mm == (None if manual_before else pytest.approx(expected))


def test_native_dimension_tolerance_exports_and_roundtrips(tmp_path: Path) -> None:
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    tolerance = DimensionTolerance("deviation", 0.02, -0.01, 3, 0.7, "top")
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        position_mm=(10, 5),
        tolerance=tolerance,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    target = tmp_path / "tolerance.dxf"
    write_sketches_dxf((sketch,), target)
    readfile = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])
    document = readfile(target)
    native = next(entity for entity in document.modelspace() if entity.dxftype() == "DIMENSION")
    override = native.override()
    assert override.get("dimtol") == 1
    assert override.get("dimtp") == 0.02
    assert override.get("dimtm") == 0.01
    assert override.get("dimtdec") == 3
    assert override.get("dimtfac") == 0.7
    restored = read_sketch_dxf(target).sketch.constraints[0]
    assert restored.tolerance == tolerance

    override["dimtp"] = 0.04
    override["dimtm"] = -0.01
    override.commit()
    document.saveas(target)
    changed = read_sketch_dxf(target).sketch.constraints[0]
    assert changed.tolerance == DimensionTolerance("deviation", 0.04, 0.01, 3, 0.7, "top")


@pytest.mark.parametrize("magnitude", [0.1, 1e-12])
def test_changed_angular_unit_converts_native_tolerances_to_degrees(
    tmp_path: Path, magnitude: float
) -> None:
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (0, 0), (0, 10))
    dimension = SketchConstraint(
        uuid4().hex,
        "angle",
        (
            SketchGeometryReference(first.entity_id, "geometry"),
            SketchGeometryReference(second.entity_id, "geometry"),
        ),
        90,
        "deg",
        driving=False,
        tolerance=DimensionTolerance("deviation", 0.1, -0.2),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second), (dimension,))
    target = tmp_path / "angular-unit-change.dxf"
    write_sketches_dxf((sketch,), target)
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(target)
    native = next(entity for entity in document.modelspace() if entity.dxftype() == "DIMENSION")
    override = native.override()
    override["dimaunit"] = 3
    override["dimadec"] = -1
    override["dimtp"] = magnitude
    override["dimtm"] = 2 * magnitude
    override.commit()
    document.saveas(target)
    imported = read_sketch_dxf(target)
    changed = imported.sketch.constraints[0].tolerance
    assert changed is not None
    assert changed.upper_deviation == pytest.approx(math.degrees(magnitude), abs=1e-20)
    assert changed.lower_deviation == pytest.approx(math.degrees(-2 * magnitude), abs=1e-20)
    assert changed.precision == 8
    assert imported.sketch.constraints[0].precision == 8
    assert any("角度显示单位" in message for message in imported.report.warnings)
    assert any(
        "非零公差" in message and "显示为零" in message for message in imported.report.warnings
    ) == (magnitude < 1e-10)


@pytest.mark.parametrize("mode", ["none", "symmetric", "deviation", "limits"])
def test_scaled_dxf_restores_inherited_dimension_tolerance(tmp_path: Path, mode: str) -> None:
    from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable

    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    tolerance = DimensionTolerance(
        mode,
        0 if mode == "none" else 0.02,
        0 if mode == "none" else -0.02 if mode == "symmetric" else -0.01,
    )
    style = DimensionStyle("检验", linear_tolerance=tolerance)
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        style_name=style.name,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    target = tmp_path / "inherited-inch.dxf"
    write_sketches_dxf(
        (sketch,), target, dimension_styles=DimensionStyleTable((style,), style.name)
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(target)
    document.header["$INSUNITS"] = 1
    document.saveas(target)
    imported = read_sketch_dxf(target)
    restored = imported.sketch.constraints[0].tolerance
    assert restored is not None
    assert restored.mode == mode
    assert restored.upper_deviation == pytest.approx(tolerance.upper_deviation * 25.4)
    assert restored.lower_deviation == pytest.approx(tolerance.lower_deviation * 25.4)
    assert restored.precision == 3
    assert imported.sketch.constraints[0].precision == 3
    assert any("公差" in warning for warning in imported.report.warnings)
    reexport = tmp_path / "inherited-restored.dxf"
    write_sketches_dxf((imported.sketch,), reexport)
    assert read_sketch_dxf(reexport).sketch.constraints[0].tolerance == restored


@pytest.mark.parametrize("mode", ["symmetric", "deviation", "limits"])
def test_native_tolerance_survives_removed_style_metadata(tmp_path: Path, mode: str) -> None:
    from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable

    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    tolerance = DimensionTolerance(mode, 0.02, -0.02 if mode == "symmetric" else -0.01)
    style = DimensionStyle("检验", linear_tolerance=tolerance)
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        style_name=style.name,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    target = tmp_path / "removed-style.dxf"
    write_sketches_dxf(
        (sketch,), target, dimension_styles=DimensionStyleTable((style,), style.name)
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(target)
    native = document.modelspace().query("DIMENSION")[0]
    native.discard_xdata("MYCAD_DIMENSION_STYLE")
    document.saveas(target)
    imported = read_sketch_dxf(target)
    assert imported.sketch.constraints[0].tolerance == tolerance
    assert any("公差" in warning and "覆盖" in warning for warning in imported.report.warnings)


@pytest.mark.parametrize("snapshot_kind", ["missing", "corrupt", "v1"])
def test_external_tolerance_wins_when_snapshot_cannot_check_style(
    tmp_path: Path, snapshot_kind: str
) -> None:
    import json

    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        tolerance=DimensionTolerance("deviation", 0.02, -0.01),
    )
    target = tmp_path / "unverified-native-tolerance.dxf"
    write_sketches_dxf((Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)),), target)
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(target)
    native = document.modelspace().query("DIMENSION")[0]
    if snapshot_kind == "v1":
        values = [
            tag.value for tag in native.get_xdata("MYCAD_DIMENSION_SNAPSHOT") if tag.code == 1000
        ]
        payload = json.loads("".join(values[1:]))
        stripped = {key: value for key, value in payload.items() if not key.startswith("style:")}
        raw = json.dumps(stripped, separators=(",", ":"))
        native.set_xdata(
            "MYCAD_DIMENSION_SNAPSHOT",
            [(1000, "1"), *[(1000, raw[i : i + 240]) for i in range(0, len(raw), 240)]],
        )
    elif snapshot_kind == "corrupt":
        native.set_xdata("MYCAD_DIMENSION_SNAPSHOT", [(1000, "8"), (1000, "invalid")])
    else:
        native.discard_xdata("MYCAD_DIMENSION_SNAPSHOT")
    override = native.override()
    override["dimtp"] = 0.04
    override["dimtm"] = 0.03
    override["dimdec"] = 4
    override.commit()
    document.saveas(target)
    imported = read_sketch_dxf(target)
    changed = imported.sketch.constraints[0].tolerance
    assert changed is not None
    assert changed.upper_deviation == pytest.approx(0.04)
    assert changed.lower_deviation == pytest.approx(-0.03)
    assert imported.sketch.constraints[0].precision == 4
    assert any("原生公差" in warning for warning in imported.report.warnings)


@pytest.mark.parametrize(
    "tolerance",
    [
        DimensionTolerance("deviation", 0.02, -0.01),
        DimensionTolerance("deviation", 0.02, -0.02),
        DimensionTolerance("none", 0.02, -0.01),
    ],
)
def test_missing_snapshot_preserves_unchanged_or_disabled_metadata(
    tmp_path: Path, tolerance: DimensionTolerance
) -> None:
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        tolerance=tolerance,
    )
    target = tmp_path / "unchanged-snapshot.dxf"
    write_sketches_dxf((Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)),), target)
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(target)
    document.modelspace().query("DIMENSION")[0].discard_xdata("MYCAD_DIMENSION_SNAPSHOT")
    document.saveas(target)
    imported = read_sketch_dxf(target)
    assert imported.sketch.constraints[0].tolerance == tolerance
    assert not any("已采用原生公差" in warning for warning in imported.report.warnings)


def test_missing_snapshot_recovers_angle_units_and_display_precision(tmp_path: Path) -> None:
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (0, 0), (0, 10))
    dimension = SketchConstraint(
        uuid4().hex,
        "angle",
        (
            SketchGeometryReference(first.entity_id, "geometry"),
            SketchGeometryReference(second.entity_id, "geometry"),
        ),
        90,
        "deg",
        driving=False,
        tolerance=DimensionTolerance("deviation", 0.1, -0.2),
    )
    target = tmp_path / "missing-angle-snapshot.dxf"
    write_sketches_dxf(
        (Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second), (dimension,)),), target
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(target)
    native = document.modelspace().query("DIMENSION")[0]
    native.discard_xdata("MYCAD_DIMENSION_SNAPSHOT")
    override = native.override()
    override["dimaunit"] = 3
    override["dimadec"] = -1
    override.commit()
    document.saveas(target)
    imported = read_sketch_dxf(target)
    restored = imported.sketch.constraints[0]
    assert restored.tolerance is not None
    assert restored.tolerance.upper_deviation == pytest.approx(math.degrees(0.1))
    assert restored.tolerance.lower_deviation == pytest.approx(math.degrees(-0.2))
    assert restored.tolerance.precision == restored.precision == 8
    assert any("角度显示单位" in warning for warning in imported.report.warnings)


@pytest.mark.parametrize("inherited", [False, True])
def test_invalid_external_tolerance_does_not_restore_stale_metadata(
    tmp_path: Path, inherited: bool
) -> None:
    from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable

    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    tolerance = DimensionTolerance("deviation", 0.02, -0.01)
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        style_name="检验" if inherited else None,
        tolerance=None if inherited else tolerance,
    )
    styles = DimensionStyleTable((DimensionStyle("检验", linear_tolerance=tolerance),), "检验")
    target = tmp_path / "invalid-external-tolerance.dxf"
    write_sketches_dxf(
        (Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)),),
        target,
        dimension_styles=styles if inherited else None,
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(target)
    native = document.modelspace().query("DIMENSION")[0]
    override = native.override()
    override["dimtol"] = 1
    override["dimlim"] = 1
    override.commit()
    document.saveas(target)
    imported = read_sketch_dxf(target)
    assert not imported.sketch.constraints
    assert len(imported.sketch.entities) == 1
    assert any(
        "公差不受支持" in warning and "未恢复" in warning for warning in imported.report.warnings
    )


def test_invalid_native_tolerance_with_missing_snapshot_is_not_silently_restored(
    tmp_path: Path,
) -> None:
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        tolerance=DimensionTolerance("deviation", 0.02, -0.01),
    )
    target = tmp_path / "invalid-native.dxf"
    write_sketches_dxf((Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)),), target)
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(target)
    native = document.modelspace().query("DIMENSION")[0]
    native.discard_xdata("MYCAD_DIMENSION_SNAPSHOT")
    override = native.override()
    override["dimtol"] = 1
    override["dimlim"] = 1
    override.commit()
    document.saveas(target)
    imported = read_sketch_dxf(target)
    assert not imported.sketch.constraints
    assert any("原生公差不受支持" in warning for warning in imported.report.warnings)


@pytest.mark.parametrize("field", ["dimtp", "dimtm", "dimtfac"])
def test_external_subnanounit_tolerance_change_is_not_ignored(tmp_path: Path, field: str) -> None:
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        tolerance=DimensionTolerance("deviation", 0.01, -0.01, 8),
    )
    target = tmp_path / "small-change.dxf"
    write_sketches_dxf((Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)),), target)
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(target)
    native = document.modelspace().query("DIMENSION")[0]
    override = native.override()
    override[field] = 1.0000000005 if field == "dimtfac" else 0.0100000005
    override.commit()
    document.saveas(target)
    imported = read_sketch_dxf(target)
    tolerance = imported.sketch.constraints[0].tolerance
    assert tolerance is not None
    actual = {
        "dimtp": tolerance.upper_deviation,
        "dimtm": -tolerance.lower_deviation,
        "dimtfac": tolerance.text_factor,
    }[field]
    assert actual == pytest.approx(1.0000000005 if field == "dimtfac" else 0.0100000005, abs=1e-13)
    assert any("外部公差设置已恢复" in warning for warning in imported.report.warnings)


def test_unchanged_high_precision_native_tolerance_does_not_look_modified(tmp_path: Path) -> None:
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    tolerance = DimensionTolerance(
        "deviation", 0.1 + 0.2, -0.12345678901234566, 8, 1.0000000000000002
    )
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        tolerance=tolerance,
    )
    target = tmp_path / "unmodified-high-precision.dxf"
    write_sketches_dxf((Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)),), target)
    imported = read_sketch_dxf(target)
    assert imported.sketch.constraints[0].tolerance == tolerance
    assert not any("外部公差设置已恢复" in warning for warning in imported.report.warnings)


def test_external_precision_edit_preserves_equal_deviation_mode(tmp_path: Path) -> None:
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    original = DimensionTolerance("deviation", 0.02, -0.02, 2)
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        tolerance=original,
    )
    target = tmp_path / "equal-deviation.dxf"
    write_sketches_dxf((Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)),), target)
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(target)
    native = document.modelspace().query("DIMENSION")[0]
    override = native.override()
    override["dimtdec"] = 3
    override.commit()
    document.saveas(target)
    imported = read_sketch_dxf(target)
    assert imported.sketch.constraints[0].tolerance == replace(original, precision=3)


def test_import_scales_linear_tolerance_with_declared_units(tmp_path: Path) -> None:
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    tol = DimensionTolerance("deviation", 0.02, -0.01)
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        position_mm=(10, 5),
        tolerance=tol,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    target = tmp_path / "inch.dxf"
    write_sketches_dxf((sketch,), target)
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(target)
    document.header["$INSUNITS"] = 1
    document.saveas(target)
    actual = read_sketch_dxf(target).sketch.constraints[0].tolerance
    assert actual is not None
    assert actual.upper_deviation == pytest.approx(0.02 * 25.4)
    assert actual.lower_deviation == pytest.approx(-0.01 * 25.4)
    assert (
        replace(
            actual,
            upper_deviation=tol.upper_deviation,
            lower_deviation=tol.lower_deviation,
            precision=tol.precision,
        )
        == tol
    )
    assert actual.precision == 3


@pytest.mark.parametrize("kind", ["ordinate", "angle", "radius", "diameter", "arc_length"])
@pytest.mark.parametrize("mode", ["symmetric", "deviation", "limits"])
def test_dimension_kinds_export_structured_tolerance(tmp_path: Path, kind: str, mode: str) -> None:
    first = LineEntity(uuid4().hex, (0, 0), (30, 0))
    second = LineEntity(uuid4().hex, (0, 0), (0, 40))
    circle = CircleEntity(uuid4().hex, (60, 50), 10)
    arc = ArcEntity(uuid4().hex, (80, 50), 10, 0, 90)
    tol = DimensionTolerance(mode, 0.02, -0.02 if mode == "symmetric" else -0.01)
    if kind == "angle":
        refs = (
            SketchGeometryReference(first.entity_id, "geometry"),
            SketchGeometryReference(second.entity_id, "geometry"),
        )
        dimension = SketchConstraint(
            uuid4().hex, "angle", refs, 90, "deg", driving=False, tolerance=tol
        )
        entities = (first, second)
    elif kind in ("radius", "diameter"):
        dimension = SketchConstraint(
            uuid4().hex,
            kind,
            (SketchGeometryReference(circle.entity_id, "geometry"),),
            10 if kind == "radius" else 20,
            "mm",
            driving=False,
            tolerance=tol,
        )
        entities = (circle,)
    elif kind == "arc_length":
        dimension = SketchConstraint(
            uuid4().hex,
            "arc_length",
            (SketchGeometryReference(arc.entity_id, "geometry"),),
            15.707963267949,
            "mm",
            driving=False,
            tolerance=tol,
        )
        entities = (arc,)
    else:
        dimension = SketchConstraint(
            uuid4().hex,
            "length",
            (SketchGeometryReference(first.entity_id, "geometry"),),
            30,
            "mm",
            driving=False,
            axis="ordinate_x",
            tolerance=tol,
        )
        entities = (first,)
    target = tmp_path / f"{kind}-{mode}.dxf"
    write_sketches_dxf((Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities, (dimension,)),), target)
    assert read_sketch_dxf(target).sketch.constraints[0].tolerance == tol
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(target)
    native = next(
        entity
        for entity in document.modelspace()
        if entity.dxftype() in ("DIMENSION", "ARC_DIMENSION")
    )
    override = native.override()
    assert override.get("dimtol") == (0 if mode == "limits" else 1)
    assert override.get("dimlim") == (1 if mode == "limits" else 0)
    assert override.get("dimtp") == pytest.approx(tol.upper_deviation)
    assert override.get("dimtm") == pytest.approx(-tol.lower_deviation)


@pytest.mark.parametrize("inherited", [False, True])
def test_dimension_with_hidden_tolerance_is_not_exported_as_zero(
    tmp_path: Path, inherited: bool
) -> None:
    from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable

    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    tolerance = DimensionTolerance("symmetric", 1e-10, -1e-10, 8)
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        tolerance=None if inherited else tolerance,
        style_name="标准" if inherited else None,
    )
    target = tmp_path / "tiny-tolerance.dxf"
    styles = DimensionStyleTable((DimensionStyle("标准", linear_tolerance=tolerance),), "标准")
    report = write_sketches_dxf(
        (Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)),),
        target,
        dimension_styles=styles if inherited else None,
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(target)
    assert not document.modelspace().query("DIMENSION")
    assert any("精度" in warning and "未导出" in warning for warning in report.warnings)


def test_equal_rounded_deviations_are_not_exported(tmp_path: Path) -> None:
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    tolerance = DimensionTolerance("deviation", 0.0124, 0.0116, 2)
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        tolerance=tolerance,
    )
    target = tmp_path / "rounded-deviations.dxf"
    report = write_sketches_dxf(
        (Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)),), target
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(target)
    assert not document.modelspace().query("DIMENSION")
    assert any("精度" in warning and "未导出" in warning for warning in report.warnings)


def test_overflowing_limit_is_not_exported_as_nonfinite_dimension(tmp_path: Path) -> None:
    line = LineEntity(uuid4().hex, (0, 0), (1e308, 0))
    tolerance = DimensionTolerance("limits", 1e308, 0)
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        1e308,
        "mm",
        tolerance=tolerance,
    )
    target = tmp_path / "overflow-limits.dxf"
    report = write_sketches_dxf(
        (Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)),), target
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(target)
    assert not document.modelspace().query("DIMENSION")
    assert any("极限" in warning and "未导出" in warning for warning in report.warnings)


def test_negative_ordinate_limits_native_block_uses_signed_values(tmp_path: Path) -> None:
    line = LineEntity(uuid4().hex, (0, 0), (-10, 0))
    tolerance = DimensionTolerance("limits", 0.1, -0.2)
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        -10,
        "mm",
        driving=False,
        axis="ordinate_x",
        tolerance=tolerance,
    )
    target = tmp_path / "ordinate-limits.dxf"
    write_sketches_dxf((Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)),), target)
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(target)
    native = document.modelspace().query("DIMENSION")[0]
    labels = [
        item.dxf.text for item in document.blocks[native.dxf.geometry] if item.dxftype() == "MTEXT"
    ]
    assert len(labels) == 1
    assert "-9.90" in labels[0] and "-10.20" in labels[0]
    assert read_sketch_dxf(target).sketch.constraints[0].tolerance == tolerance


@pytest.mark.parametrize("lower", [-0.011, -0.03])
def test_limits_crossing_zero_export_consistent_graphic(tmp_path: Path, lower: float) -> None:
    line = LineEntity(uuid4().hex, (0, 0), (0.01, 0))
    tolerance = DimensionTolerance("limits", 0.01, lower, 2)
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        0.01,
        "mm",
        tolerance=tolerance,
    )
    target = tmp_path / "cross-zero.dxf"
    write_sketches_dxf((Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)),), target)
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(target)
    native = document.modelspace().query("DIMENSION")[0]
    label = next(
        item.dxf.text for item in document.blocks[native.dxf.geometry] if item.dxftype() == "MTEXT"
    )
    assert "0.02" in label
    assert ("0.00" if lower == -0.011 else "-0.02") in label
    assert "-0.00" not in label
    assert read_sketch_dxf(target).sketch.constraints[0].tolerance == tolerance


@pytest.mark.parametrize("kind", ("length", "radius", "diameter"))
@pytest.mark.parametrize("custom", (False, True))
def test_limits_graphics_preserve_dimension_affixes(
    tmp_path: Path, kind: Literal["length", "radius", "diameter"], custom: bool
) -> None:
    entity = (
        LineEntity(uuid4().hex, (0, 0), (10, 0))
        if kind == "length"
        else CircleEntity(uuid4().hex, (0, 0), 10)
    )
    value = 20 if kind == "diameter" else 10
    dimension = SketchConstraint(
        uuid4().hex,
        kind,
        (SketchGeometryReference(entity.entity_id, "geometry"),),
        value,
        "mm",
        driving=False,
        text_override="A<>B" if custom else None,
        tolerance=DimensionTolerance("limits", 0.1, -0.2),
    )
    target = tmp_path / "affixes.dxf"
    write_sketches_dxf((Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,), (dimension,)),), target)
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(target)
    native = document.modelspace().query("DIMENSION")[0]
    label = next(
        item.dxf.text for item in document.blocks[native.dxf.geometry] if item.dxftype() == "MTEXT"
    )
    prefix = "A" if custom else {"length": "", "radius": "R", "diameter": "⌀"}[kind]
    suffix = "B" if custom else " mm"
    assert f"{prefix}{value + 0.1:.2f}{suffix}" in label
    assert f"{prefix}{value - 0.2:.2f}{suffix}" in label


def test_limits_graphics_preserve_literal_caret_text(tmp_path: Path) -> None:
    from ezdxf.tools.text import plain_mtext

    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        text_override="A^I<>B",
        tolerance=DimensionTolerance("limits", 0.1, -0.2),
    )
    target = tmp_path / "caret.dxf"
    write_sketches_dxf((Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)),), target)
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(target)
    native = document.modelspace().query("DIMENSION")[0]
    label = next(
        item.dxf.text for item in document.blocks[native.dxf.geometry] if item.dxftype() == "MTEXT"
    )
    assert plain_mtext(label) == "(A^I10.10B)\n(A^I9.80B)"


@pytest.mark.parametrize("custom", (False, True))
def test_angle_limits_graphics_include_single_correct_suffix(tmp_path: Path, custom: bool) -> None:
    from ezdxf.tools.text import plain_mtext

    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (0, 0), (0, 10))
    refs = (
        SketchGeometryReference(first.entity_id, "geometry"),
        SketchGeometryReference(second.entity_id, "geometry"),
    )
    dimension = SketchConstraint(
        uuid4().hex,
        "angle",
        refs,
        90,
        "deg",
        driving=False,
        text_override="A<>B" if custom else None,
        tolerance=DimensionTolerance("limits", 0.1, -0.2),
    )
    target = tmp_path / "angular-limits.dxf"
    write_sketches_dxf(
        (Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second), (dimension,)),), target
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(target)
    native = document.modelspace().query("DIMENSION")[0]
    label = next(
        item.dxf.text for item in document.blocks[native.dxf.geometry] if item.dxftype() == "MTEXT"
    )
    assert plain_mtext(label) == ("(A90.10B)\n(A89.80B)" if custom else "(90.10°)\n(89.80°)")


@pytest.mark.parametrize("driving", (True, False))
def test_limit_dimension_preserves_reference_parentheses_in_dxf(
    tmp_path: Path, driving: bool
) -> None:
    from ezdxf.tools.text import plain_mtext

    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=driving,
        text_override="A<>B",
        tolerance=DimensionTolerance("limits", 0.1, -0.2),
    )
    path = tmp_path / "reference-limits.dxf"
    write_sketches_dxf((Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)),), path)
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    native = document.modelspace().query("DIMENSION")[0]
    label = next(
        item.dxf.text for item in document.blocks[native.dxf.geometry] if item.dxftype() == "MTEXT"
    )
    assert plain_mtext(label) == ("A10.10B\nA9.80B" if driving else "(A10.10B)\n(A9.80B)")
    assert read_sketch_dxf(path).sketch.constraints[0].driving is driving


@pytest.mark.parametrize("kind", ("length", "radius", "diameter"))
@pytest.mark.parametrize("mode", ("symmetric", "deviation"))
def test_reference_tolerance_graphics_include_parentheses(
    tmp_path: Path, kind: Literal["length", "radius", "diameter"], mode: str
) -> None:
    from ezdxf.tools.text import plain_mtext

    entity = (
        LineEntity(uuid4().hex, (0, 0), (10, 0))
        if kind == "length"
        else CircleEntity(uuid4().hex, (0, 0), 10)
    )
    value = 20 if kind == "diameter" else 10
    dimension = SketchConstraint(
        uuid4().hex,
        kind,
        (SketchGeometryReference(entity.entity_id, "geometry"),),
        value,
        "mm",
        driving=False,
        tolerance=DimensionTolerance(mode, 0.1, -0.1 if mode == "symmetric" else -0.2),
    )
    path = tmp_path / "reference-tolerance.dxf"
    write_sketches_dxf((Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,), (dimension,)),), path)
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    native = document.modelspace().query("DIMENSION")[0]
    label = next(
        item.dxf.text for item in document.blocks[native.dxf.geometry] if item.dxftype() == "MTEXT"
    )
    prefix = {"length": "", "radius": "R", "diameter": "⌀"}[kind]
    assert f"({prefix}{value:.2f} mm)" in plain_mtext(label)
    assert read_sketch_dxf(path).sketch.constraints[0].driving is False


@pytest.mark.parametrize("kind", ("radius", "diameter", "angle"))
def test_reference_custom_tolerance_text_does_not_add_implicit_affixes(
    tmp_path: Path, kind: Literal["radius", "diameter", "angle"]
) -> None:
    from ezdxf.tools.text import plain_mtext

    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (0, 0), (0, 10))
    circle = CircleEntity(uuid4().hex, (0, 0), 10)
    entities = (first, second) if kind == "angle" else (circle,)
    refs = (
        (
            SketchGeometryReference(first.entity_id, "geometry"),
            SketchGeometryReference(second.entity_id, "geometry"),
        )
        if kind == "angle"
        else (SketchGeometryReference(circle.entity_id, "geometry"),)
    )
    value = 90 if kind == "angle" else 20 if kind == "diameter" else 10
    dimension = SketchConstraint(
        uuid4().hex,
        kind,
        refs,
        value,
        "deg" if kind == "angle" else "mm",
        driving=False,
        text_override="A<>B",
        tolerance=DimensionTolerance("symmetric", 0.1, -0.1),
    )
    path = tmp_path / "custom-reference.dxf"
    write_sketches_dxf((Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities, (dimension,)),), path)
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    native = document.modelspace().query("DIMENSION")[0]
    label = next(
        item.dxf.text for item in document.blocks[native.dxf.geometry] if item.dxftype() == "MTEXT"
    )
    assert f"(A{value:.2f}B)" in plain_mtext(label)
