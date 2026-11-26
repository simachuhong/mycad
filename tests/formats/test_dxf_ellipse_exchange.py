# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Native DXF ellipse parameters retain exact sketch geometry."""

import math
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol, cast
from uuid import uuid4

import ezdxf.filemanagement as filemanagement
import pytest

from mycad.core.sketch import EllipseEntity


class EllipseAttributes(Protocol):
    center: Iterable[float]
    major_axis: Iterable[float]
    ratio: float
    start_param: float
    end_param: float


class EllipseRecord(Protocol):
    dxf: EllipseAttributes


class QueryResult(Protocol):
    first: EllipseRecord | None


class Modelspace(Protocol):
    def add_ellipse(
        self,
        *,
        center: tuple[float, float, float],
        major_axis: tuple[float, float, float],
        ratio: float,
        start_param: float,
        end_param: float,
    ) -> object: ...

    def query(self, query: str) -> QueryResult: ...


class Document(Protocol):
    def modelspace(self) -> Modelspace: ...

    def saveas(self, path: Path) -> None: ...


class NewDocument(Protocol):
    def __call__(self, version: str) -> Document: ...


class ReadDocument(Protocol):
    def __call__(self, path: Path) -> Document: ...


@pytest.mark.parametrize("sweep", [120.0, -120.0, 360.0, -360.0])
def test_native_ellipse_roundtrip_preserves_direction_and_seam(
    tmp_path: Path, sweep: float
) -> None:
    from mycad.formats.ellipse_exchange import ellipse_from_dxf, ellipse_to_dxf

    source = EllipseEntity(uuid4().hex, (12, -8), 9, 4, 35, 25, sweep)
    data = ellipse_to_dxf(source)
    document = cast("NewDocument", vars(filemanagement)["new"])("R2010")
    document.modelspace().add_ellipse(
        center=data.center,
        major_axis=data.major_axis,
        ratio=data.ratio,
        start_param=data.start_param,
        end_param=data.end_param,
    )
    target = tmp_path / "ellipse.dxf"
    document.saveas(target)
    restored = (
        cast("ReadDocument", vars(filemanagement)["readfile"])(target)
        .modelspace()
        .query("ELLIPSE")
        .first
    )
    assert restored is not None
    result = ellipse_from_dxf(
        uuid4().hex,
        tuple(restored.dxf.center),
        tuple(restored.dxf.major_axis),
        restored.dxf.ratio,
        restored.dxf.start_param,
        restored.dxf.end_param,
        clockwise=sweep < 0,
        full_start_deg=source.start_angle_deg if source.closed else None,
    )
    for index in range(11):
        assert result.point_at(index / 10) == pytest.approx(source.point_at(index / 10), abs=1e-8)


def test_invalid_or_nonplanar_dxf_ellipse_is_rejected() -> None:
    from mycad.formats.ellipse_exchange import ellipse_from_dxf

    identity = uuid4().hex
    for center, axis, ratio in (
        ((0, 0, 1), (5, 0, 0), 0.5),
        ((0, 0, 0), (5, 0, 1), 0.5),
        ((0, 0, 0), (5, 0, 0), 1.1),
        ((0, 0, 0), (5, 0, 0), math.nan),
    ):
        with pytest.raises(ValueError):
            ellipse_from_dxf(identity, center, axis, ratio, 0, math.tau)
    with pytest.raises(ValueError):
        ellipse_from_dxf(identity, (0, 0, 0), (5, 0, 0), 0.5, 0, math.tau, normal=(0, 0, -1))


@pytest.mark.parametrize("sweep", [-120.0, 360.0, -360.0])
def test_sketch_dxf_roundtrip_preserves_ellipse_semantics(tmp_path: Path, sweep: float) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketch_dxf

    source = EllipseEntity(uuid4().hex, (12, -8), 9, 4, 35, 25, sweep)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    path = tmp_path / "sketch-ellipse.dxf"
    write_sketch_dxf(sketch, path)
    imported = read_sketch_dxf(path)
    assert len(imported.sketch.entities) == 1
    restored = imported.sketch.entities[0]
    assert isinstance(restored, EllipseEntity)
    assert restored.entity_id == source.entity_id
    for index in range(11):
        assert restored.point_at(index / 10) == pytest.approx(source.point_at(index / 10), abs=1e-8)
