# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Prepare immutable DXF output and render it with ezdxf's drawing backend."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

from mycad.core.ports import ExportableKernel
from mycad.formats.dxf_datum import DatumGraphicSnapshot, DatumNativeSnapshot
from mycad.formats.geometric_tolerance_preview import FrameGlyphs
from mycad.formats.providers.dxf_provider import (
    DXF_PROVIDER,
    DxfExchangeReport,
    write_dxf_graphics_intermediate,
    write_dxf_with_frame_anchors,
)

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


def prepare_dxf_output_preview(
    geometry: ExportableKernel,
    *,
    tolerance_graphics: bool = False,
    legacy_frame_anchors: Mapping[str, tuple[float, float]] | None = None,
    legacy_frame_skipped_vertices: Mapping[str, int] | None = None,
    legacy_frame_bounds: Mapping[str, tuple[float, float, float, float]] | None = None,
    graphic_frame_widths: Mapping[str, tuple[tuple[float, ...], ...]] | None = None,
    graphic_frame_glyphs: Mapping[str, FrameGlyphs] | None = None,
    graphic_datum_snapshots: Mapping[str, DatumGraphicSnapshot] | None = None,
    legacy_datum_snapshots: Mapping[str, DatumNativeSnapshot] | None = None,
) -> DxfOutputPreview:
    """Render actual DXF dimension blocks, curves and layers without writing a destination.

    Drawing dependencies are loaded only for the desktop preview. Ordinary
    headless DXF exchange retains its existing dependency surface.
    """
    if not tolerance_graphics and (
        graphic_frame_widths or graphic_frame_glyphs or graphic_datum_snapshots
    ):
        raise ValueError("图形布局快照仅适用于图形兼容导出。")
    if tolerance_graphics and legacy_datum_snapshots:
        raise ValueError("旧基准原生布局快照仅适用于原生导出。")
    import ezdxf.filemanagement as filemanagement

    from mycad.formats.dxf_datum import (
        DATUM_APPID,
        freeze_datum_blocks,
        has_compressed_datum_metadata,
        outline_wide_datum_blocks,
    )
    from mycad.formats.geometric_tolerance_preview import expand_tolerances_for_preview

    read_dxf = cast("Callable[[Path], Drawing]", vars(filemanagement)["readfile"])
    with tempfile.TemporaryDirectory(prefix="mycad-dxf-preview-") as directory:
        path = Path(directory) / "output.dxf"
        if tolerance_graphics:
            report = write_dxf_graphics_intermediate(
                geometry,
                path,
                legacy_frame_anchors=legacy_frame_anchors,
                legacy_frame_skipped_vertices=legacy_frame_skipped_vertices,
                legacy_frame_bounds=legacy_frame_bounds,
            )
        elif (
            legacy_frame_anchors
            or legacy_frame_skipped_vertices
            or legacy_frame_bounds
            or legacy_datum_snapshots is not None
        ):
            report = write_dxf_with_frame_anchors(
                geometry,
                path,
                legacy_frame_anchors or {},
                legacy_frame_skipped_vertices,
                legacy_frame_bounds,
                legacy_datum_snapshots=legacy_datum_snapshots,
            )
        else:
            report = DXF_PROVIDER.write(geometry, path)
        if not isinstance(report, DxfExchangeReport):
            raise ValueError("DXF 导出没有返回交换报告。")
        document = read_dxf(path)
        if tolerance_graphics:
            converted_group_names = tuple(
                name
                for name, group in document.groups
                if any(member.dxftype() == "TOLERANCE" for member in group)
            )
            converted, unsupported = expand_tolerances_for_preview(
                document,
                outline_wide_text=True,
                strict=True,
                frame_widths=graphic_frame_widths,
                frame_glyphs=graphic_frame_glyphs,
            )
            if unsupported or document.modelspace().query("TOLERANCE"):
                raise ValueError("存在无法转换为兼容图形的形位公差；未生成导出文件。")
            try:
                frozen_datums = freeze_datum_blocks(document, graphic_datum_snapshots or {})
                datum_outlines = outline_wide_datum_blocks(document)
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise ValueError(f"基准图形转换失败：{exc}") from exc
            remaining_datum_text = any(
                insert.has_xdata(DATUM_APPID)
                and bool(document.blocks[insert.dxf.name].query("TEXT"))
                for insert in document.modelspace().query("INSERT")
            )
            if remaining_datum_text:
                report = replace(
                    report,
                    warnings=(
                        *report.warnings,
                        "未取得画布基准字形快照，目标 CAD 字体替代可能改变文字外观或使文字越框。",
                    ),
                )
            if converted or datum_outlines or frozen_datums:
                compressed_datums_remain = has_compressed_datum_metadata(document)
                with path.open("w", encoding="utf-8", newline="") as stream:
                    document.write(stream)
                from mycad.formats.providers.dxf_provider import read_sketch_dxf

                readback_warnings = read_sketch_dxf(path).report.warnings
                lost_attachments = tuple(
                    warning
                    for warning in readback_warnings
                    if "标注附着目标无法恢复" in warning
                    or ("表面延伸线" in warning and "关联" in warning)
                    or "失关联的表面指示" in warning
                )
                lost_groups = tuple(
                    warning
                    for warning in readback_warnings
                    if warning.startswith("组 ")
                    and ("无法完整或唯一恢复" in warning or "没有可恢复成员" in warning)
                )
                report = replace(
                    report,
                    entity_count=len(document.modelspace()),
                    warnings=(
                        *(
                            (
                                "旧公差框自动布线在图形兼容导出中无法恢复，仅保留可见路径。"
                                if warning.startswith("旧公差框自动布线仅由本软件扩展数据恢复")
                                else "旧公差框隐藏法向约束在图形兼容导出中无法恢复，仅保留可见路径。"
                                if warning.startswith("旧公差框隐藏法向约束仅由本软件扩展数据恢复")
                                else warning
                            )
                            for warning in report.warnings
                            if not warning.startswith(
                                (
                                    "公差框以原生 TOLERANCE 导出；",
                                    "大型形位公差元数据已压缩；",
                                    "原生公差框的目标 CAD 排版",
                                )
                            )
                            and (
                                compressed_datums_remain
                                or not warning.startswith("大型基准元数据已压缩；")
                            )
                            and not (
                                frozen_datums
                                and warning.startswith("基准文字样式 ")
                                and warning.endswith("未指定字体文件，其他 CAD 可能替代字体。")
                            )
                            and not (
                                frozen_datums and warning.startswith("旧基准框及引线按导出字体估算")
                            )
                        ),
                        *(
                            (
                                f"{converted} 个形位公差框已转换为近似图形，不可作为结构化公差编辑或无损恢复。",
                                *(
                                    (
                                        "公差框框格按当前画布字体度量；目标 CAD 字体替代可能导致文字溢出。"
                                        if graphic_frame_widths
                                        else "公差框框格按估算字宽绘制，引线连接可能存在偏差。",
                                    )
                                    if not graphic_frame_glyphs
                                    else ()
                                ),
                            )
                            if converted
                            else ()
                        ),
                        *lost_attachments,
                        *lost_groups,
                        *(
                            f"组 {name} 的公差框已转换为代理图形，无法恢复为原结构化成员。"
                            for name in converted_group_names
                        ),
                        *(
                            (
                                f"{frozen_datums} 个基准标识已转换为画布图形与填充文字，无法恢复结构化基准信息。",
                            )
                            if frozen_datums
                            else ()
                        ),
                        *(
                            (
                                f"{datum_outlines} 个基准标识的宽文字已转换为空心轮廓，外观可能不同于画布，无法恢复结构化基准信息。",
                            )
                            if datum_outlines
                            else ()
                        ),
                    ),
                )
                document = read_dxf(path)
        payload = path.read_bytes()
        return _render_dxf_document(document, payload, report)


def prepare_dxf_bytes_preview(payload: bytes, report: DxfExchangeReport) -> DxfOutputPreview:
    """Render precisely the DXF bytes that the caller will later write."""
    import ezdxf.filemanagement as filemanagement

    read_dxf = cast("Callable[[Path], Drawing]", vars(filemanagement)["readfile"])
    with tempfile.TemporaryDirectory(prefix="mycad-dxf-bytes-preview-") as directory:
        path = Path(directory) / "output.dxf"
        path.write_bytes(payload)
        return _render_dxf_document(read_dxf(path), payload, report)


def _render_dxf_document(
    document: Drawing, payload: bytes, report: DxfExchangeReport
) -> DxfOutputPreview:
    from ezdxf.addons.drawing import layout, svg
    from ezdxf.addons.drawing.config import BackgroundPolicy, Configuration
    from ezdxf.addons.drawing.frontend import Frontend
    from ezdxf.addons.drawing.properties import RenderContext
    from ezdxf.math import BoundingBox2d

    from mycad.formats.geometric_tolerance_preview import expand_tolerances_for_preview

    rendered, unsupported = expand_tolerances_for_preview(document)
    backend = svg.SVGBackend()
    Frontend(
        RenderContext(document),
        backend,
        config=Configuration(background_policy=BackgroundPolicy.WHITE),
    ).draw_layout(document.modelspace())
    bounds = backend.player().bbox()
    notices: tuple[str, ...] = ()
    if rendered:
        notices += ("形位公差预览按导出内容绘制，文字宽度为估算；其他 CAD 软件的排版可能不同。",)
    if unsupported:
        notices += (f"{unsupported} 个形位公差无法预览。",)
    if not bounds.has_data:
        bounds = BoundingBox2d(((0.0, 0.0), (1.0, 1.0)))
        notices += ("当前图层设置下没有可见图元；隐藏图元仍保存在 DXF 中。",)
    image = backend.get_string(
        layout.Page(297, 210, margins=layout.Margins.all(10)), render_box=bounds
    )
    return DxfOutputPreview(payload, image.encode("utf-8"), report, notices)
