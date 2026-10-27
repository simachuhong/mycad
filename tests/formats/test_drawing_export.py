# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Engineering DXF preserves exact curves and physical paper coordinates."""

from dataclasses import replace
from pathlib import Path

import pytest

from mycad.formats.drawing_export import export_drawing_dxf
from tests.helpers.drawing_scene import drawing_scene


def tags(path: Path) -> list[tuple[int, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [(int(a.strip()), b.strip()) for a, b in zip(lines[::2], lines[1::2], strict=True)]


def test_dxf_sheet_blocks_scale_and_units(tmp_path: Path) -> None:
    path = tmp_path / "drawing.dxf"
    export_drawing_dxf(drawing_scene(), path)
    data = tags(path)
    index = data.index((9, "$INSUNITS"))
    assert data[index + 1] == (70, "4")
    assert (0, "INSERT") in data
    index = data.index((0, "INSERT"))
    end = next(i for i in range(index + 1, len(data)) if data[i][0] == 0)
    insertion = dict(data[index + 1 : end])
    assert float(insertion[41]) == float(insertion[42]) == 0.5
    assert float(insertion[10]) == 60 and float(insertion[20]) == 130
    assert insertion[67] == "1"  # paperspace
    assert (1, "80.00 mm") in data
    assert (0, "ELLIPSE") in data and (0, "SPLINE") in data
    assert (0, "POLYLINE") not in data and (0, "LWPOLYLINE") not in data


def test_export_matches_frozen_scene(tmp_path: Path) -> None:
    scene = drawing_scene()
    path = tmp_path / "drawing.dxf"
    export_drawing_dxf(scene, path)
    data = tags(path)
    assert (11, "80.0") in data  # original line endpoint remains model mm in block
    assert (1, "名称：法兰工程图") in data
    assert scene.views[0].to_paper((80, 0)) == (100, 130)
    assert (2, "HIDDEN") in data and (2, "DIM") in data


def test_invalid_scene_preserves_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "existing.dxf"
    path.write_bytes(b"original")
    with pytest.raises(ValueError, match="更新"):
        export_drawing_dxf(replace(drawing_scene(), issues=("请更新视图",)), path)
    assert path.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [path]


def test_annotation_layer_is_preserved_in_scene_and_dxf(tmp_path: Path) -> None:
    from mycad.core.drawing_annotations import resolve_annotation
    from mycad.core.drawing_paper import paper_texts
    from mycad.core.drawing_projection import ProjectionResult

    scene = drawing_scene()
    annotation = replace(scene.annotations[0], layer="MEASURE")
    # Resolve through the real shared path rather than decorating an output DTO.
    view = scene.views[0]
    resolved = resolve_annotation(
        annotation, ProjectionResult(view.view_id, "fixture", 1, view.curves), view
    )
    assert resolved.layer == "MEASURE"
    scene = replace(scene, annotations=(annotation,), resolved_annotations=(resolved,))
    assert paper_texts(scene)[-1].layer == "MEASURE"
    path = tmp_path / "layer.dxf"
    export_drawing_dxf(scene, path)
    data = tags(path)
    assert (2, "MEASURE") in data and (8, "MEASURE") in data
