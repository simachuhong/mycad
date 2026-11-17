# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""View-space editing must preserve its world-space meaning across sketches."""

import pytest

from mycad.core.cross_sketch_tangency import project_coplanar_rotation, project_coplanar_vector
from mycad.core.sketch import WorkPlaneFrame


@pytest.mark.parametrize(
    ("frame", "expected_vector", "expected_angle"),
    [
        (WorkPlaneFrame((5, 7, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1)), (2, -4), 90),
        (WorkPlaneFrame((5, 7, 0), (-1, 0, 0), (0, 1, 0), (0, 0, -1)), (-4, 2), -90),
    ],
)
def test_view_edit_transform_across_frames(
    frame: WorkPlaneFrame, expected_vector: tuple[int, int], expected_angle: int
) -> None:
    view = WorkPlaneFrame.xy()
    assert project_coplanar_vector((4, 2), view, frame) == pytest.approx(expected_vector)
    assert project_coplanar_rotation(90, view, frame) == expected_angle


def test_view_edit_transform_rejects_non_coplanar_frames() -> None:
    with pytest.raises(ValueError, match="共面"):
        project_coplanar_vector((1, 0), WorkPlaneFrame.xy(), WorkPlaneFrame.xz())
    with pytest.raises(ValueError, match="共面"):
        project_coplanar_rotation(90, WorkPlaneFrame.xy(), WorkPlaneFrame.xz())
