# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Hand-written declarations for the pyqtgraph.opengl surface MyCAD uses.

pyqtgraph ships no ``py.typed`` marker, so ``basedpyright`` in strict mode
rejects ``import pyqtgraph.opengl`` with reportMissingTypeStubs. These stubs
declare **only** the names ``src/mycad/ui/viewport.py`` (and its test) touch.
They are declarations of an existing runtime API, not suppressions: the
zero-suppression scan in tests/test_layering.py stays green because nothing
here is an ``ignore`` comment.

The shape is pinned to the locked range ``pyqtgraph>=0.13,<0.14``, where
``GLGraphicsItem`` is a ``QObject`` (not a ``QWidget``), ``GLViewWidget`` is a
``QOpenGLWidget``, and ``MeshData`` takes ``vertexes``/``faces``. That range
has no ``GLLineSegmentItem``, so the wireframe edges are drawn with
``GLLinePlotItem(mode="lines")`` — documented as "each pair of vertexes draws
a single line segment", i.e. exactly the segment list the plan asks for.
"""

from collections.abc import Sequence
from typing import Any

import numpy as np
from PySide6.QtCore import QObject
from PySide6.QtGui import QQuaternion, QVector3D
from PySide6.QtOpenGLWidgets import QOpenGLWidget

_Array = np.ndarray[Any, np.dtype[Any]]
_FloatArray = np.ndarray[Any, np.dtype[np.float32]]
_IntArray = np.ndarray[Any, np.dtype[np.int32]]

class GLGraphicsItem(QObject):
    def __init__(self, parentItem: GLGraphicsItem | None = None) -> None: ...
    def setGLOptions(self, opts: str) -> None: ...
    def setVisible(self, vis: bool) -> None: ...
    def visible(self) -> bool: ...

class GLViewWidget(QOpenGLWidget):
    opts: dict[str, Any]
    items: list[GLGraphicsItem]
    def __init__(self, *, rotationMethod: str = ...) -> None: ...
    def addItem(self, item: GLGraphicsItem) -> None: ...
    def removeItem(self, item: GLGraphicsItem) -> None: ...
    def setCameraPosition(
        self,
        pos: QVector3D | None = ...,
        distance: float | None = ...,
        elevation: float | None = ...,
        azimuth: float | None = ...,
        rotation: QQuaternion | None = ...,
    ) -> None: ...
    def cameraPosition(self) -> QVector3D: ...
    def setBackgroundColor(self, *args: Any) -> None: ...
    def setOptions(self, **kwds: Any) -> None: ...

class MeshData:
    def __init__(
        self,
        vertexes: _FloatArray | Sequence[Sequence[float]] | None = ...,
        faces: _IntArray | Sequence[Sequence[int]] | None = ...,
        edges: _Array | None = ...,
        vertexColors: _FloatArray | None = ...,
        faceColors: _FloatArray | None = ...,
    ) -> None: ...
    def faces(self) -> _IntArray | None: ...
    def vertexes(self, indexed: str | None = ...) -> _FloatArray: ...

class GLMeshItem(GLGraphicsItem):
    def __init__(self, parentItem: GLGraphicsItem | None = ..., **kwds: Any) -> None: ...
    def setMeshData(self, **kwds: Any) -> None: ...
    def setColor(self, c: Any) -> None: ...

class GLLinePlotItem(GLGraphicsItem):
    def __init__(self, parentItem: GLGraphicsItem | None = ..., **kwds: Any) -> None: ...
    def setData(self, **kwds: Any) -> None: ...
