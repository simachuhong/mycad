# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Prepare immutable DXF output and render it with ezdxf's drawing backend."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from mycad.core.ports import ExportableKernel
from mycad.formats.providers.dxf_provider import DXF_PROVIDER, DxfExchangeReport

if TYPE_CHECKING:
    from ezdxf.document import Drawing


@dataclass(frozen=True, slots=True)
class DxfOutputPreview:
    """The image and exchange report describe these exact export bytes."""

    dxf_bytes: bytes
    svg_bytes: bytes
    report: DxfExchangeReport
    notices: tuple[str, ...] = ()

    def write(self, path: Path) -> None:
        """Replace a destination atomically, leaving it intact on write failure."""
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
            ) as stream:
                temporary = Path(stream.name)
                stream.write(self.dxf_bytes)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def prepare_dxf_output_preview(geometry: ExportableKernel) -> DxfOutputPreview:
    """Render actual DXF dimension blocks, curves and layers without writing a destination.

    Drawing dependencies are loaded only for the desktop preview. Ordinary
    headless DXF exchange retains its existing dependency surface.
    """
    import ezdxf.filemanagement as filemanagement
    from ezdxf.addons.drawing import layout, svg
    from ezdxf.addons.drawing.config import BackgroundPolicy, Configuration
    from ezdxf.addons.drawing.frontend import Frontend
    from ezdxf.addons.drawing.properties import RenderContext
    from ezdxf.math import BoundingBox2d

    read_dxf = cast("Callable[[Path], Drawing]", vars(filemanagement)["readfile"])
    with tempfile.TemporaryDirectory(prefix="mycad-dxf-preview-") as directory:
        path = Path(directory) / "output.dxf"
        report = DXF_PROVIDER.write(geometry, path)
        if not isinstance(report, DxfExchangeReport):
            raise ValueError("DXF 导出没有返回交换报告。")
        payload = path.read_bytes()
        document = read_dxf(path)
        backend = svg.SVGBackend()
        Frontend(
            RenderContext(document),
            backend,
            config=Configuration(background_policy=BackgroundPolicy.WHITE),
        ).draw_layout(document.modelspace())
        bounds = backend.player().bbox()
        notices: tuple[str, ...] = ()
        if not bounds.has_data:
            bounds = BoundingBox2d(((0.0, 0.0), (1.0, 1.0)))
            notices = ("当前图层设置下没有可见图元；隐藏图元仍保存在 DXF 中。",)
        image = backend.get_string(
            layout.Page(297, 210, margins=layout.Margins.all(10)), render_box=bounds
        )
    return DxfOutputPreview(payload, image.encode("utf-8"), report, notices)
