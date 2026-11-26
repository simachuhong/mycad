# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Dimension tolerance styles survive the command history."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest

from mycad import app
from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
from mycad.core.dimension_tolerance import DimensionTolerance
from mycad.core.exceptions import ValidationError
from mycad.core.persistence import save_document
from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.formats.providers.dxf_provider import write_sketches_dxf


@pytest.mark.parametrize(
    ("fixture", "upper", "lower"),
    [
        ("cadcraft-dimension-edited.dxf", 0.04, 0.01),
        ("cadcraft-angle-edited.dxf", 0.5729577951308232, -1.1459155902616465),
    ],
)
def test_cadcraft_tolerance_import_survives_history_and_save(
    tmp_path: Path, fixture: str, upper: float, lower: float
) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    source = Path(__file__).parents[1] / "fixtures/dxf" / fixture
    imported = read_sketch_dxf(source)
    expected = imported.sketch.constraints[0]
    assert expected.tolerance is not None
    assert expected.tolerance.upper_deviation == pytest.approx(upper)
    assert expected.tolerance.lower_deviation == pytest.approx(lower)
    assert expected.text_position_mm is None
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    app.commit_new_sketch(services, loaded, imported.sketch, session_identity=0)
    assert services.kernel.sketches[0].constraints == (expected,)
    loaded.bus.undo_operation()
    assert not services.kernel.sketches
    loaded.bus.redo_operation()
    assert services.kernel.sketches[0].constraints == (expected,)
    path = tmp_path / "external-tolerance.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.sketches[0].constraints == (expected,)


def test_missing_dxf_style_tolerance_survives_import_history_and_save(tmp_path: Path) -> None:
    import ezdxf.filemanagement as filemanagement

    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    tolerance = DimensionTolerance("deviation", 0.02, -0.01)
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
    source = tmp_path / "without-style.dxf"
    write_sketches_dxf(
        (sketch,), source, dimension_styles=DimensionStyleTable((style,), style.name)
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(source)
    document.modelspace().query("DIMENSION")[0].discard_xdata("MYCAD_DIMENSION_STYLE")
    document.saveas(source)
    imported = read_sketch_dxf(source)
    assert imported.sketch.constraints[0].tolerance == tolerance
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    app.commit_new_sketch(services, loaded, imported.sketch, session_identity=0)
    assert services.kernel.sketches[0].constraints[0].tolerance == tolerance
    loaded.bus.undo_operation()
    assert not services.kernel.sketches
    loaded.bus.redo_operation()
    assert services.kernel.sketches[0].constraints[0].tolerance == tolerance
    target = tmp_path / "restored-style.my2d"
    save_document(loaded.document, target)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, target)
    assert reopened.kernel.sketches[0].constraints[0].tolerance == tolerance


def test_tolerance_style_replay_undo_and_old_schema(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    tolerance = DimensionTolerance("deviation", 0.02, -0.01, 3)
    table = DimensionStyleTable((DimensionStyle("标准", linear_tolerance=tolerance),), "标准")
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.dimension_styles.set", table.to_mapping(), "local", version=8)
    assert not loaded.document.commands
    loaded.bus.execute("drawing.dimension_styles.set", table.to_mapping(), "local", version=9)
    assert services.kernel.drawing_dimension_styles == table
    loaded.bus.undo()
    assert services.kernel.drawing_dimension_styles.current.linear_tolerance.mode == "none"
    loaded.bus.redo()
    path = tmp_path / "tolerance.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_dimension_styles == table


def test_cross_zero_limits_save_reopen_and_replay_without_changing_geometry(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (0.01, 0))
    tolerance = DimensionTolerance("limits", 0.01, -0.03, 2)
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        0.01,
        "mm",
        tolerance=tolerance,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    assert services.kernel.sketches[0].entities == (line,)
    path = tmp_path / "cross-zero.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches[0].constraints[0].tolerance == tolerance
    assert reopened_services.kernel.sketches[0].entities == (line,)
    reopened.bus.undo_operation()
    assert not reopened_services.kernel.sketches
    reopened.bus.redo_operation()
    assert reopened_services.kernel.sketches[0].constraints[0].tolerance == tolerance
    assert reopened_services.kernel.sketches[0].entities == (line,)


def test_dimension_text_style_reference_is_versioned_and_protected(tmp_path: Path) -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    text_styles = TextStyleTable((TextStyle(), TextStyle("inspect", "检验")), "standard")
    loaded.bus.execute("drawing.text_styles.set", text_styles.to_mapping(), "local")
    dimensions = DimensionStyleTable((DimensionStyle("标准", text_style_id="inspect"),), "标准")
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.dimension_styles.set", dimensions.to_mapping(), "local", version=9
        )
    loaded.bus.execute("drawing.dimension_styles.set", dimensions.to_mapping(), "local", version=10)
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.text_styles.set", TextStyleTable().to_mapping(), "local")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        style_name="标准",
        position_mm=(5, 5),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    app.move_tolerance_selection(
        services, loaded, (line.entity_id,), (), (), (), (1, 2), session_identity=0
    )
    target = tmp_path / "dimension-style-font.my2d"
    save_document(loaded.document, target)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, target)
    assert reopened.kernel.drawing_dimension_styles == dimensions
    assert reopened.kernel.drawing_text_styles == text_styles
    assert reopened.kernel.sketches[0].constraints[0].position_mm == (6, 7)


def test_dxf_roundtrips_native_dimension_font_reference(tmp_path: Path) -> None:
    import ezdxf.filemanagement as filemanagement

    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        style_name="检验",
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    table = DimensionStyleTable((DimensionStyle("检验", text_style_id="inspect"),), "检验")
    path = tmp_path / "font.dxf"
    fonts = TextStyleTable((TextStyle("inspect", "检验字体", "DejaVu Sans"),), "inspect")
    report = write_sketches_dxf((sketch,), path, dimension_styles=table, text_styles=fonts)
    assert not any("文字样式引用" in warning for warning in report.warnings)
    assert any("未指定字体文件" in warning for warning in report.warnings)
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    native = next(iter(document.modelspace().query("DIMENSION")))
    assert native.override().get("dimtxsty") == "检验字体"
    imported = read_sketch_dxf(path)
    imported_id = imported.dimension_styles[0][1].text_style_id
    assert imported_id is not None and imported.text_styles is not None
    assert imported.text_styles.get(imported_id).font_family == "DejaVu Sans"
    document.styles.get("检验字体").set_extended_font_data(
        "External Font", italic=False, bold=False
    )
    document.saveas(path)
    changed = read_sketch_dxf(path)
    changed_id = changed.dimension_styles[0][1].text_style_id
    assert changed_id is not None and changed.text_styles is not None
    assert changed.text_styles.get(changed_id).font_family == "External Font"


def test_clipboard_cannot_replace_existing_text_style() -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    previous_fonts = services.kernel.drawing_text_styles
    previous_dimensions = services.kernel.drawing_dimension_styles
    conflicting = TextStyleTable((TextStyle(font_family="changed"),))
    params = {
        "layers": services.kernel.drawing_layers.to_mapping(),
        "dimension_layer": "DIM",
        "assignments": [],
        "clipboard_styles": previous_dimensions.to_mapping(),
        "clipboard_text_styles": conflicting.to_mapping(),
    }
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.clipboard.prepare", params, "local", version=8)
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.clipboard.prepare", params, "local", version=9)
    assert services.kernel.drawing_text_styles == previous_fonts
    assert services.kernel.drawing_dimension_styles == previous_dimensions
    assert not loaded.document.commands


def test_dimension_override_has_new_schema_and_reopens(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
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
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    write_sketches_dxf((sketch,), tmp_path / "tolerance.dxf")
    with pytest.raises(ValidationError):
        loaded.bus.execute("sketch.create", sketch.to_state_mapping(), "local", version=32)
    loaded.bus.execute("sketch.create", sketch.to_state_mapping(), "local", version=46)
    target = tmp_path / "dimension.my2d"
    save_document(loaded.document, target)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, target)
    assert reopened.kernel.sketches[0].constraints[0].tolerance == dimension.tolerance


def test_update_dimension_tolerance_does_not_move_geometry_and_is_undoable() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    loaded.bus.execute("sketch.create", sketch.to_state_mapping(), "local", version=32)
    updated = replace(dimension, tolerance=DimensionTolerance("deviation", 0.02, -0.01))
    result = services.kernel.preview_sketch_constraint_update(sketch, updated)
    assert result.status == "success"
    candidate = app.create_replay_candidate(services, loaded, session_identity=1)
    candidate.stage(
        ReplayChangeSet(
            (),
            (
                ReplayAppend(
                    "sketch.constraint.update",
                    7,
                    result.command_params(sketch, updated, local_frame=True),
                    "local",
                ),
            ),
            False,
        ),
        current_session_identity=1,
    )
    assert candidate.preview(current_session_identity=1).state == "succeeded"
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    assert services.kernel.sketches[0].entities == (line,)
    assert services.kernel.sketches[0].constraints[0].tolerance == updated.tolerance
    loaded.bus.undo()
    assert services.kernel.sketches[0].constraints[0].tolerance is None
    loaded.bus.redo()
    assert services.kernel.sketches[0].constraints[0].tolerance == updated.tolerance


def test_commit_new_sketch_selects_tolerance_capable_command() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    dim = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        tolerance=DimensionTolerance("deviation", 0.02, -0.01),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dim,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    assert services.kernel.sketches[0].constraints[0].tolerance == dim.tolerance
    assert loaded.document.commands[-1].version == 46


def test_style_cannot_enable_tolerance_on_literal_dimension_override() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    dim = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        style_name="标准",
        text_override="固定文字",
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dim,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    table = DimensionStyleTable(
        (DimensionStyle("标准", linear_tolerance=DimensionTolerance("deviation", 0.02, -0.01)),),
        "标准",
    )
    before = loaded.document.command_count
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.dimension_styles.set", table.to_mapping(), "local")
    assert loaded.document.command_count == before
    assert services.kernel.sketches[0].constraints[0] == dim


def test_new_dimension_cannot_combine_tolerance_with_literal_text() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    dim = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        text_override="固定文字",
        tolerance=DimensionTolerance("deviation", 0.02, -0.01),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dim,))
    with pytest.raises(ValidationError):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    assert not loaded.document.commands


@pytest.mark.parametrize("on_draft", [False, True])
def test_mixed_move_preserves_dimension_tolerance(on_draft: bool) -> None:
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    draft_line = LineEntity(uuid4().hex, (20, 0), (30, 0))
    tolerance = DimensionTolerance("deviation", 0.02, -0.01)
    dim = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        tolerance=tolerance,
    )
    draft_dim = replace(
        dim, references=(SketchGeometryReference(draft_line.entity_id, "geometry"),)
    )
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), () if on_draft else (dim,))
    draft = Sketch(
        uuid4().hex, WorkPlaneFrame.xy(), (draft_line,), (draft_dim,) if on_draft else ()
    )
    moved_saved = replace(saved, entities=(replace(line, start_mm=(2, 3), end_mm=(12, 3)),))
    moved_draft = replace(draft, entities=(replace(draft_line, start_mm=(22, 3), end_mm=(32, 3)),))
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(services, loaded, saved, session_identity=1)
    candidate = app.stage_mixed_drawing_timeline(
        services, loaded, draft, (saved,), (((moved_saved,), moved_draft),), session_identity=1
    )
    preview = candidate.preview(current_session_identity=1)
    assert preview.state == "succeeded", preview.failure
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    assert any(c.tolerance == tolerance for s in services.kernel.sketches for c in s.constraints)


def test_imported_style_and_dimension_tolerance_commit_together() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    tol = DimensionTolerance("deviation", 0.02, -0.01)
    style = DimensionStyle("加工", linear_tolerance=tol)
    table = DimensionStyleTable((DimensionStyle("标准"), style), "标准")
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        style_name="加工",
        tolerance=tol,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=1, imported_styles=table)
    assert services.kernel.drawing_dimension_styles.get("加工").linear_tolerance == tol
    assert services.kernel.sketches[0].constraints[0].tolerance == tol
