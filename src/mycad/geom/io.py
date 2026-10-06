# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""geom-side export wiring (T8a): the build123d boundary for file writes.

``BuildKernel.export_step`` / ``export_stl`` delegate here. The formats
package reaches build123d only through those kernel methods, so no
build123d object ever leaves ``mycad.geom`` (layering invariant).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

import build123d
from build123d import Part

from mycad.core.exceptions import EmptyGeometryError


def write_step(part: Part | None, path: Path) -> None:
    """Write ``part`` to ``path`` as STEP; empty geometry refuses before any I/O."""

    if part is None:
        msg = f"STEP export to {path} refused: the model is empty"
        raise EmptyGeometryError(message=msg)
    # build123d annotates the exporters with bare generics (Shape / PathLike),
    # partially unknown under basedpyright strict; the cast narrows to the
    # exact call shape used here. This is a cast, not a suppression comment.
    cast(Callable[[Part, Path], bool], build123d.export_step)(part, path)


def write_stl(part: Part | None, path: Path) -> None:
    """Write ``part`` to ``path`` as an STL mesh; empty geometry refuses."""

    if part is None:
        msg = f"STL export to {path} refused: the model is empty"
        raise EmptyGeometryError(message=msg)
    cast(Callable[[Part, Path], bool], build123d.export_stl)(part, path)
