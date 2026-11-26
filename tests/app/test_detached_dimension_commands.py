# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Detached dimensions use history and remain independent of geometry."""

from pathlib import Path
from uuid import uuid4

import pytest

from mycad import app
from mycad.core.detached_dimension import DetachedDimension
from mycad.core.dimension_tolerance import DimensionTolerance
from mycad.core.exceptions import ValidationError
from mycad.core.persistence import save_document


@pytest.mark.parametrize("kind", ("radius", "diameter"))
def test_radial_reference_version_history_and_reopen(tmp_path: Path, kind: str) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    dimension = DetachedDimension(uuid4().hex, kind, (0, 0), (10, 0), (15, 0), 0, 10)
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.reference_dimensions.batch",
            {"add": [dimension.to_mapping()]},
            "local",
            version=1,
        )
    loaded.bus.execute(
        "drawing.reference_dimensions.batch", {"add": [dimension.to_mapping()]}, "local", version=2
    )
    loaded.bus.undo()
    assert not services.kernel.drawing_reference_dimensions
    loaded.bus.redo()
    path = tmp_path / "radial.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_reference_dimensions == (dimension,)


@pytest.mark.parametrize(
    ("kind", "previous", "version"), (("angular_3p", 2, 3), ("angular_2l", 3, 4))
)
def test_angular_reference_moves_vertex_and_reopens(
    tmp_path: Path, kind: str, previous: int, version: int
) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    dimension = DetachedDimension(
        uuid4().hex, kind, (10, 0), (0, 10), (5, 5), 0, 90, vertex_mm=(0, 0)
    )
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.reference_dimensions.batch",
            {"add": [dimension.to_mapping()]},
            "local",
            version=previous,
        )
    loaded.bus.execute(
        "drawing.reference_dimensions.batch",
        {"add": [dimension.to_mapping()]},
        "local",
        version=version,
    )
    app.move_tolerance_selection(
        services, loaded, (), (), (), (dimension.dimension_id,), (3, 2), session_identity=0
    )
    moved = services.kernel.drawing_reference_dimensions[0]
    assert moved.vertex_mm == (3, 2) and moved.first_mm == (13, 2)
    path = tmp_path / "angular-reference.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_reference_dimensions == (moved,)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_reference_dimensions == (dimension,)


def test_reflex_reference_version_and_history(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    dimension = DetachedDimension(
        uuid4().hex, "angular_3p", (0, 10), (10, 0), (-5, -5), 0, 270, vertex_mm=(0, 0)
    )
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.reference_dimensions.batch",
            {"add": [dimension.to_mapping()]},
            "local",
            version=6,
        )
    loaded.bus.execute(
        "drawing.reference_dimensions.batch", {"add": [dimension.to_mapping()]}, "local", version=7
    )
    loaded.bus.undo()
    assert not services.kernel.drawing_reference_dimensions
    loaded.bus.redo()
    path = tmp_path / "reflex.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_reference_dimensions == (dimension,)


@pytest.mark.parametrize("kind", ["angular_3p", "angular_2l"])
def test_import_and_move_reflex_reference_as_transaction(kind: str) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    dimension = DetachedDimension(
        uuid4().hex, kind, (0, 10), (10, 0), (-5, -5), 0, 270, vertex_mm=(0, 0)
    )
    app.commit_new_sketch(
        services,
        loaded,
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), ()),
        session_identity=0,
        imported_reference_dimensions=(dimension,),
    )
    assert services.kernel.drawing_reference_dimensions == (dimension,)
    app.move_tolerance_selection(
        services, loaded, (), (), (), (dimension.dimension_id,), (3, 2), session_identity=0
    )
    moved = services.kernel.drawing_reference_dimensions[0]
    assert moved.vertex_mm == (3, 2) and moved.nominal == 270
    loaded.bus.undo_operation()
    assert services.kernel.drawing_reference_dimensions == (dimension,)
    loaded.bus.undo_operation()
    assert not services.kernel.drawing_reference_dimensions


def test_two_line_reflex_reference_version_and_history(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    dimension = DetachedDimension(
        uuid4().hex, "angular_2l", (0, 10), (10, 0), (-5, -5), 0, 270, vertex_mm=(0, 0)
    )
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.reference_dimensions.batch",
            {"add": [dimension.to_mapping()]},
            "local",
            version=7,
        )
    loaded.bus.execute(
        "drawing.reference_dimensions.batch", {"add": [dimension.to_mapping()]}, "local", version=8
    )
    loaded.bus.undo()
    assert not services.kernel.drawing_reference_dimensions
    loaded.bus.redo()
    path = tmp_path / "two-line-reflex.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_reference_dimensions == (dimension,)


def test_three_point_straight_reference_version_and_history(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    dimension = DetachedDimension(
        uuid4().hex, "angular_3p", (10, 0), (-10, 0), (0, 15), 0, 180, vertex_mm=(0, 0)
    )
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.reference_dimensions.batch",
            {"add": [dimension.to_mapping()]},
            "local",
            version=8,
        )
    loaded.bus.execute(
        "drawing.reference_dimensions.batch", {"add": [dimension.to_mapping()]}, "local", version=9
    )
    loaded.bus.undo()
    assert not services.kernel.drawing_reference_dimensions
    loaded.bus.redo()
    path = tmp_path / "straight-angle.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_reference_dimensions == (dimension,)


@pytest.mark.parametrize(("kind", "nominal"), (("ordinate_x", 3.0), ("ordinate_y", -4.0)))
def test_rotated_ordinate_reference_version_and_history(
    tmp_path: Path, kind: str, nominal: float
) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    dimension = DetachedDimension(
        uuid4().hex,
        kind,
        (10, 20),
        (14, 23),
        (18, 28),
        90,
        nominal,
        tolerance=DimensionTolerance("deviation", 0.1, -0.2, 2),
    )
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.reference_dimensions.batch",
            {"add": [dimension.to_mapping()]},
            "local",
            version=9,
        )
    loaded.bus.execute(
        "drawing.reference_dimensions.batch",
        {"add": [dimension.to_mapping()]},
        "local",
        version=10,
    )
    loaded.bus.undo()
    assert not services.kernel.drawing_reference_dimensions
    loaded.bus.redo()
    path = tmp_path / "rotated-ordinate.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_reference_dimensions == (dimension,)


@pytest.mark.parametrize("kind", ("radius", "diameter", "angular_3p", "angular_2l"))
def test_import_new_reference_types_is_one_transaction(kind: str) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    dimension = (
        DetachedDimension(uuid4().hex, kind, (10, 0), (0, 10), (5, 5), 0, 90, vertex_mm=(0, 0))
        if kind in ("angular_3p", "angular_2l")
        else DetachedDimension(uuid4().hex, kind, (0, 0), (10, 0), (15, 0), 0, 10)
    )
    app.commit_new_sketch(
        services,
        loaded,
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), ()),
        session_identity=0,
        imported_reference_dimensions=(dimension,),
    )
    assert services.kernel.drawing_reference_dimensions == (dimension,)
    loaded.bus.undo_operation()
    assert not services.kernel.drawing_reference_dimensions


def test_detached_dimension_history_and_archive_roundtrip(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
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
    loaded.bus.execute(
        "drawing.reference_dimensions.batch", {"add": [dimension.to_mapping()]}, "local"
    )
    assert services.kernel.drawing_reference_dimensions == (dimension,)
    loaded.bus.undo()
    assert not services.kernel.drawing_reference_dimensions
    loaded.bus.redo()
    path = tmp_path / "reference.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_reference_dimensions == (dimension,)


def test_import_detached_dimension_is_one_undoable_transaction() -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    dimension = DetachedDimension(uuid4().hex, "rotated", (0, 0), (10, 0), (0, 5), 0, 10)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    app.commit_new_sketch(
        services, loaded, sketch, session_identity=0, imported_reference_dimensions=(dimension,)
    )
    assert services.kernel.drawing_reference_dimensions == (dimension,)
    loaded.bus.undo()
    assert not services.kernel.drawing_reference_dimensions


def test_detached_dimension_survives_sketch_revision_and_replay() -> None:
    from dataclasses import replace

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    dimension = DetachedDimension(uuid4().hex, "rotated", (0, 0), (10, 0), (0, 5), 0, 10)
    loaded.bus.execute(
        "drawing.reference_dimensions.batch", {"add": [dimension.to_mapping()]}, "local"
    )
    moved = replace(sketch, entities=(replace(line, end_mm=(20, 0)),))
    state = moved.to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
    )
    assert services.kernel.drawing_reference_dimensions == (dimension,)
    loaded.bus.undo()
    loaded.bus.redo()
    assert services.kernel.drawing_reference_dimensions == (dimension,)


@pytest.mark.parametrize("kind", ("ordinate_x", "ordinate_y"))
def test_ordinate_reference_version_move_and_reopen(tmp_path: Path, kind: str) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    second = (-10, 0) if kind == "ordinate_x" else (0, -10)
    dimension = DetachedDimension(uuid4().hex, kind, (0, 0), second, (5, 5), 0, -10)
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.reference_dimensions.batch",
            {"add": [dimension.to_mapping()]},
            "local",
            version=4,
        )
    loaded.bus.execute(
        "drawing.reference_dimensions.batch", {"add": [dimension.to_mapping()]}, "local", version=5
    )
    app.move_tolerance_selection(
        services, loaded, (), (), (), (dimension.dimension_id,), (3, 2), session_identity=0
    )
    moved = services.kernel.drawing_reference_dimensions[0]
    assert moved.nominal == -10 and moved.first_mm == (3, 2)
    path = tmp_path / "ordinate.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_reference_dimensions == (moved,)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_reference_dimensions == (dimension,)
