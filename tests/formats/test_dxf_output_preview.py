# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Render the prepared DXF and export those exact bytes after acceptance."""

from pathlib import Path
from xml.etree import ElementTree

import pytest

from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
from mycad.formats.dxf_preview import prepare_dxf_output_preview
from mycad.formats.providers.dxf_provider import read_sketch_dxf
from mycad.geom.kernel import BuildKernel


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
