# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Read a conservative native DXF reference-only dimension subset."""

from __future__ import annotations

import math
import re
from typing import Any
from uuid import uuid4

from ezdxf import bbox

from mycad.core.detached_dimension import DetachedDimension
from mycad.core.dimension_tolerance import DimensionTolerance, tolerance_values_hidden_by_precision
from mycad.formats.dxf_units import scaled_length_precision

REFERENCE_DIMENSION_APPID = "MYCAD_REFERENCE_DIMENSION"
ORDINATE_AXIS_SNAPSHOT_PREFIX = "ORDINATE_AXIS_V1:"
ORDINATE_TYPE_SNAPSHOT_PREFIX = "ORDINATE_TYPE_V1:"


def ordinate_axis_snapshot_warnings(
    metadata: tuple[str, ...], dimension: DetachedDimension, handle: str
) -> tuple[str, ...]:
    """Report changed or malformed optional ordinate snapshots without overriding native data."""
    warnings: list[str] = []
    angles = tuple(
        value[len(ORDINATE_AXIS_SNAPSHOT_PREFIX) :]
        for value in metadata
        if value.startswith(ORDINATE_AXIS_SNAPSHOT_PREFIX)
    )
    if angles:
        try:
            if len(angles) != 1:
                raise ValueError("duplicate ordinate axis snapshot")
            saved_angle = float(angles[0])
            if not math.isfinite(saved_angle):
                raise ValueError("invalid ordinate axis snapshot")
            if dimension.kind not in ("ordinate_x", "ordinate_y") or not math.isclose(
                math.remainder(saved_angle - dimension.angle_deg, 360.0), 0.0, abs_tol=1e-10
            ):
                warnings.append(
                    f"坐标尺寸 {handle} 的坐标轴方向已改变，已采用原生方向和数值，请核对。"
                )
        except ValueError:
            warnings.append(f"坐标尺寸 {handle} 的坐标轴方向快照无效，请核对。")
    axes = tuple(
        value[len(ORDINATE_TYPE_SNAPSHOT_PREFIX) :]
        for value in metadata
        if value.startswith(ORDINATE_TYPE_SNAPSHOT_PREFIX)
    )
    if axes:
        if len(axes) != 1 or axes[0] not in ("ordinate_x", "ordinate_y"):
            warnings.append(f"坐标尺寸 {handle} 的坐标轴类型快照无效，请核对。")
        elif axes[0] != dimension.kind:
            warnings.append(f"坐标尺寸 {handle} 的坐标轴类型已改变，已采用原生类型和数值，请核对。")
    return tuple(warnings)


def angular_tolerance_factor_to_degrees(unit: int) -> float:
    """Convert a DXF angular tolerance value in DIMAUNIT to decimal degrees."""
    factors = {0: 1.0, 1: 1.0, 2: 0.9, 3: 180.0 / math.pi}
    if unit not in factors:
        raise ValueError(f"角度公差单位代码 {unit} 不受支持")
    return factors[unit]


def angular_precision_in_degrees(unit: int, precision: int) -> int:
    """Retain decimal precision when angular values are converted to degrees."""
    if not 0 <= precision <= 8:
        raise ValueError("角度精度超出支持范围")
    angular_tolerance_factor_to_degrees(unit)
    if unit == 2:
        return min(precision + 1, 8)
    return 8 if unit == 3 else precision


def angular_dimension_graphics(entity: Any) -> tuple[Any, ...] | None:
    """Return native dimension graphics, or None when they cannot be inspected."""
    try:
        geometry = entity.dxf.get("geometry", None)
        if not geometry or entity.doc is None or entity.doc.blocks.get(geometry) is None:
            return None
        graphics = tuple(entity.virtual_entities())
        if not any(item.dxftype() in ("ARC", "MTEXT", "TEXT") for item in graphics):
            return None
        return graphics
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        return None


def angular_graphic_shows_only_nominal(entity: Any) -> bool:
    """Recognize a plain nominal-only angle in a native dimension graphic."""
    if entity.dxf.get("text", "") not in ("", "<>"):
        return False
    graphics = angular_dimension_graphics(entity)
    if graphics is None:
        return False
    labels = [item for item in graphics if item.dxftype() in ("MTEXT", "TEXT")]
    if len(labels) != 1:
        return False
    label = labels[0]
    text = label.plain_text() if label.dxftype() == "MTEXT" else label.dxf.text
    return (
        re.fullmatch(
            r"\s*[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)\s*(?:°|%%d|r|g)?\s*",
            text,
            re.IGNORECASE,
        )
        is not None
    )


def angular_dimension_has_inspectable_arc(
    graphics: tuple[Any, ...], dimension: DetachedDimension, scale: float
) -> bool:
    """Recognize a circular dimension arc at the represented vertex and radius."""
    vertex = dimension.vertex_mm
    if vertex is None:
        return False
    radius = math.dist(vertex, dimension.location_mm)
    for item in graphics:
        if item.dxftype() != "ARC":
            continue
        try:
            center = _xy(item.dxf.center, scale)
            actual_radius = float(item.dxf.radius) * scale
        except (AttributeError, TypeError, ValueError, OverflowError):
            continue
        if math.isclose(math.dist(center, vertex), 0, abs_tol=1e-7) and math.isclose(
            actual_radius, radius, rel_tol=1e-7, abs_tol=1e-7
        ):
            return True
    return False


def angular_graphic_omits_tolerance(entity: Any, dimension: DetachedDimension) -> bool:
    """Recognize a plain nominal-only angular graphic despite tolerance fields."""
    return (
        dimension.kind in ("angular_3p", "angular_2l")
        and dimension.tolerance.mode != "none"
        and dimension.text_override in ("", "<>")
        and angular_graphic_shows_only_nominal(entity)
    )


def correct_ordinate_limit_graphics(renderer: Any, nominal: float) -> None:
    """Correct ezdxf's absolute-value ordinate limits in the generated block.

    Keep the native DIMENSION and its tolerance overrides unchanged. The renderer's
    own tolerance formatter supplies decimal separators and zero suppression.
    """
    renderer.tol.update_limits(nominal)
    block = renderer.dimension.doc.blocks[renderer.dimension.dxf.geometry]
    labels = list(block.query("MTEXT"))
    if len(labels) != 1:
        raise ValueError("坐标尺寸图形中的极限值文字无法安全修正")
    labels[0].dxf.text = renderer.tol.compile_mtext(renderer.measurement.text)


def apply_limit_text_affixes(renderer: Any, template: str, *, angular: bool = False) -> None:
    """Apply the dimension's visible text to both formatted limits.

    ezdxf omits dimension text for limit-mode MTEXT. Use separate paragraphs
    so literal stack delimiters in a custom prefix or suffix stay literal.
    """
    if template.count("<>") != 1:
        raise ValueError("极限尺寸文字需要一个 <> 占位符")
    # DXF caret sequences encode control characters even outside stacked text.
    template = template.replace("^", "^ ")
    labels = list(renderer.dimension.doc.blocks[renderer.dimension.dxf.geometry].query("MTEXT"))
    if len(labels) != 1:
        raise ValueError("极限尺寸图形中的文字无法安全修正")
    upper_value = renderer.tol.text_upper
    lower_value = renderer.tol.text_lower
    if angular:
        upper_value = upper_value.removesuffix("°")
        lower_value = lower_value.removesuffix("°")

    def normalize_negative_zero(value: str) -> str:
        if value.startswith("-"):
            try:
                if float(value.replace(",", ".")) == 0:
                    return value[1:]
            except ValueError:
                pass
        return value

    upper_value = normalize_negative_zero(upper_value)
    lower_value = normalize_negative_zero(lower_value)
    upper = template.replace("<>", upper_value)
    lower = template.replace("<>", lower_value)
    labels[0].dxf.text = f"{{\\H{renderer.tol.text_scale_factor:.2f}x;{upper}\\P{lower}}}"


def apply_dimension_main_text(
    renderer: Any, *, reference: bool, kind: str, template: str | None
) -> None:
    """Match canvas reference notation and custom text in native graphics."""
    labels = list(renderer.dimension.doc.blocks[renderer.dimension.dxf.geometry].query("MTEXT"))
    if len(labels) != 1:
        raise ValueError("参考尺寸图形中的文字无法安全修正")
    if template is None:
        main = renderer.measurement.text
        if kind == "diameter" and main.startswith("%%c"):
            main = "⌀" + main[3:]
        elif kind == "diameter" and main.startswith("Ø"):
            main = "⌀" + main[1:]
    else:
        number = renderer.measurement.format_text(renderer.measurement.value)
        if kind == "radius":
            number = number.removeprefix("R")
        elif kind == "diameter":
            number = number.removeprefix("Ø").removeprefix("%%c")
        elif kind == "angle":
            number = number.removesuffix("°")
        main = template.replace("<>", number, 1)
    main = main.replace("^", "^ ")
    labels[0].dxf.text = renderer.tol.compile_mtext(f"({main})" if reference else main)


def clear_angular_tolerance_text(renderer: Any) -> None:
    """Clip dimension arcs against the generated text's conservative bounds."""
    block = renderer.dimension.doc.blocks[renderer.dimension.dxf.geometry]
    labels = list(block.query("MTEXT"))
    if len(labels) != 1:
        raise ValueError("角度公差图形中的文字无法安全留白")
    label = labels[0]
    proxy = label.copy()
    stacked = re.search(r"(?<!\\)\\S([^;^]*)\^ ?([^;]*);", proxy.text)
    if stacked is not None:
        upper, lower = stacked.group(1), stacked.group(2)
        longest, shortest = sorted((upper, lower), key=len, reverse=True)
        proxy.text = (
            proxy.text[: stacked.start()] + longest + r"\P" + shortest + proxy.text[stacked.end() :]
        )
        proxy.dxf.char_height *= max(1.0, float(renderer.tol.text_scale_factor))
    bounds = bbox.extents([proxy])
    if not bounds.has_data:
        raise ValueError("角度公差文字边界无法计算")
    padding = max(float(proxy.dxf.char_height) * 0.05, 1e-7)
    left, bottom = bounds.extmin.x - padding, bounds.extmin.y - padding
    right, top = bounds.extmax.x + padding, bounds.extmax.y + padding
    center = renderer.center_of_arc
    expected_radius = float(renderer.dim_line_radius)
    for arc in list(block.query("ARC")):
        x0, y0 = float(arc.dxf.center.x), float(arc.dxf.center.y)
        radius = float(arc.dxf.radius)
        if not math.isclose(
            math.hypot(x0 - center.x, y0 - center.y), 0, abs_tol=1e-7
        ) or not math.isclose(radius, expected_radius, rel_tol=1e-7, abs_tol=1e-7):
            continue
        start = float(arc.dxf.start_angle)
        span = (float(arc.dxf.end_angle) - start) % 360
        breaks = [0.0, span]
        for boundary, origin, vertical in (
            (left, x0, True),
            (right, x0, True),
            (bottom, y0, False),
            (top, y0, False),
        ):
            ratio = (boundary - origin) / radius
            if not -1 <= ratio <= 1:
                continue
            angle = math.degrees(math.acos(ratio) if vertical else math.asin(ratio))
            candidates = (angle, -angle) if vertical else (angle, 180 - angle)
            for candidate in candidates:
                offset = (candidate - start) % 360
                if 1e-9 < offset < span - 1e-9:
                    breaks.append(offset)
        breaks = sorted(set(breaks))
        kept: list[tuple[float, float]] = []
        for lower, upper in zip(breaks, breaks[1:], strict=False):
            angle = math.radians(start + (lower + upper) / 2)
            x, y = x0 + radius * math.cos(angle), y0 + radius * math.sin(angle)
            if not (left < x < right and bottom < y < top):
                if kept and math.isclose(kept[-1][1], start + lower, abs_tol=1e-9):
                    kept[-1] = (kept[-1][0], start + upper)
                else:
                    kept.append((start + lower, start + upper))
        if not kept:
            block.delete_entity(arc)
            continue
        for lower, upper in kept[1:]:
            extra = arc.copy()
            extra.dxf.start_angle, extra.dxf.end_angle = lower % 360, upper % 360
            block.add_entity(extra)
        arc.dxf.start_angle, arc.dxf.end_angle = kept[0][0] % 360, kept[0][1] % 360


def _xy(value: Any, scale: float) -> tuple[float, float]:
    if len(value) < 2 or (len(value) > 2 and not math.isclose(float(value[2]), 0, abs_tol=1e-9)):
        raise ValueError("仅支持 XY 平面的尺寸")
    return float(value[0]) * scale, float(value[1]) * scale


def _line_intersection(
    first: tuple[float, float],
    first_end: tuple[float, float],
    second: tuple[float, float],
    second_end: tuple[float, float],
) -> tuple[float, float]:
    u = (first_end[0] - first[0], first_end[1] - first[1])
    v = (second_end[0] - second[0], second_end[1] - second[1])
    determinant = u[0] * v[1] - u[1] * v[0]
    if not math.isfinite(determinant) or abs(determinant) <= 1e-12:
        raise ValueError("两线角度尺寸的两条线平行或无效")
    delta = (second[0] - first[0], second[1] - first[1])
    t = (delta[0] * v[1] - delta[1] * v[0]) / determinant
    point = (first[0] + t * u[0], first[1] + t * u[1])
    if not all(math.isfinite(coordinate) for coordinate in point):
        raise ValueError("两线角度尺寸的交点无效")
    return point


def _check_angular_dimension_graphics(
    entity: Any,
    scale: float,
    vertex: tuple[float, float],
    first: tuple[float, float],
    location: tuple[float, float],
    nominal: float,
) -> None:
    """Reject visible dimension arcs demonstrably outside the measured sector."""
    radius = math.dist(vertex, location)
    start = math.degrees(math.atan2(first[1] - vertex[1], first[0] - vertex[0])) % 360
    graphics = angular_dimension_graphics(entity)
    if graphics is None:
        return
    for graphic in graphics:
        if graphic.dxftype() != "ARC":
            continue
        center = _xy(graphic.dxf.center, scale)
        arc_radius = float(graphic.dxf.radius) * scale
        if not math.isclose(math.dist(center, vertex), 0, abs_tol=1e-7) or not math.isclose(
            arc_radius, radius, rel_tol=1e-7, abs_tol=1e-7
        ):
            continue
        angle = float(graphic.dxf.start_angle)
        span = (float(graphic.dxf.end_angle) - angle) % 360
        for fraction in (0.01, 0.25, 0.5, 0.75, 0.99):
            relative = (angle + fraction * span - start) % 360
            if nominal + 1e-5 < relative < 360 - 1e-5:
                # Renderers may add short dimension-line extensions outside
                # either arrow when text or arrows do not fit inside the arc.
                distance = min(relative - nominal, 360 - relative)
                if span <= 10 and distance <= 2.1 * span + 1e-5:
                    continue
                raise ValueError("角度图形与角度定义不一致")
    # Some CAD programs replace the dimension arc with short connected chords.
    # Only examine runs of at least three chords on the expected circle; a lone
    # line touching the circle can instead be an extension or leader line.
    chords: list[tuple[tuple[float, float], tuple[float, float]]] = []
    endpoints: dict[tuple[float, float], list[int]] = {}
    for graphic in graphics:
        if graphic.dxftype() != "LINE":
            continue
        try:
            a, b = _xy(graphic.dxf.start, scale), _xy(graphic.dxf.end, scale)
        except (AttributeError, TypeError, ValueError, OverflowError):
            continue
        if (
            not math.isclose(math.dist(a, vertex), radius, rel_tol=1e-7, abs_tol=1e-7)
            or not math.isclose(math.dist(b, vertex), radius, rel_tol=1e-7, abs_tol=1e-7)
            or not 1e-12 < math.dist(a, b) <= radius * 0.25
        ):
            continue
        index = len(chords)
        chords.append((a, b))
        for point in (a, b):
            endpoints.setdefault((round(point[0], 7), round(point[1], 7)), []).append(index)
    remaining = set(range(len(chords)))
    while remaining:
        pending = [remaining.pop()]
        component: list[int] = []
        while pending:
            index = pending.pop()
            component.append(index)
            for point in chords[index]:
                key = (round(point[0], 7), round(point[1], 7))
                for neighbour in endpoints.pop(key, []):
                    if neighbour in remaining:
                        remaining.remove(neighbour)
                        pending.append(neighbour)
        if len(component) < 3:
            continue
        for index in component:
            a, b = chords[index]
            for point in (a, b):
                angle = math.degrees(math.atan2(point[1] - vertex[1], point[0] - vertex[0]))
                relative = (angle - start) % 360
                if nominal + 1e-5 < relative < 360 - 1e-5:
                    raise ValueError("角度图形与角度定义不一致")


def read_native_tolerance(
    style: Any, *, angular: bool, scale: float, default_precision: int = 2
) -> DimensionTolerance:
    """Read an effective native tolerance and convert it to the document units."""
    enabled, limits = int(style.get("dimtol", 0)), int(style.get("dimlim", 0))
    if enabled not in (0, 1) or limits not in (0, 1) or enabled + limits > 1:
        raise ValueError("公差模式不支持")
    angular_unit = int(style.get("dimaunit", 0)) if angular else 0
    factor = angular_tolerance_factor_to_degrees(angular_unit) if angular else scale
    upper = float(style.get("dimtp", 0)) * factor
    lower = -float(style.get("dimtm", 0)) * factor
    mode = (
        "limits"
        if limits
        else "symmetric"
        if enabled and upper >= 0 and upper == -lower
        else "deviation"
        if enabled
        else "none"
    )
    alignments = {0: "bottom", 1: "middle", 2: "top"}
    alignment = int(style.get("dimtolj", 0))
    if alignment not in alignments:
        raise ValueError("公差对齐不支持")
    precision = int(style.get("dimtdec", default_precision))
    precision = (
        angular_precision_in_degrees(angular_unit, precision)
        if angular
        else scaled_length_precision(precision, scale)
    )
    return DimensionTolerance(
        mode, upper, lower, precision, float(style.get("dimtfac", 1)), alignments[alignment]
    )


def read_detached_dimension(entity: Any, scale: float) -> DetachedDimension:
    """Read supported native dimensions without claiming a geometry association."""
    dimtype = int(entity.dxf.dimtype)
    kind = dimtype & 15
    own_reference = bool(entity.has_xdata(REFERENCE_DIMENSION_APPID))
    if (dimtype & 128 and not (own_reference and kind in (3, 4))) or float(
        entity.dxf.get("text_rotation", 0.0)
    ) != 0:
        raise ValueError("自定义尺寸文字位置或旋转不受支持")
    raw_text = str(entity.dxf.get("text", ""))
    if any(token in raw_text for token in ("\\", "{", "}", "%%")):
        raise ValueError("尺寸文字格式控制不受支持")
    if kind not in (0, 1, 2, 3, 4, 5, 6):
        raise ValueError("只支持外部线性、对齐、半径、直径、角度或坐标尺寸")
    extrusion = entity.dxf.get("extrusion", (0, 0, 1))
    if math.dist(extrusion, (0, 0, 1)) > 1e-9:
        raise ValueError("仅支持 XY 平面的尺寸")
    style = entity.override()
    angular_unit = int(style.get("dimaunit", 0)) if kind in (2, 5) else 0
    precision = int(style.get("dimadec" if kind in (2, 5) else "dimdec", 2))
    if kind in (2, 5) and precision == -1:
        precision = int(style.get("dimdec", 2))
    tolerance = read_native_tolerance(
        style, angular=kind in (2, 5), scale=scale, default_precision=precision
    )
    if kind in (2, 5):
        precision = angular_precision_in_degrees(angular_unit, precision)
    else:
        precision = scaled_length_precision(precision, scale)
    factor = 1.0 if kind in (2, 5) else float(style.get("dimlfac", 1))
    ordinate_angle = 0.0
    if kind == 6:
        direction = float(entity.dxf.get("horizontal_direction", 0))
        if not math.isfinite(direction):
            raise ValueError("坐标尺寸方向角无效")
        ordinate_angle = -math.remainder(direction, 360.0)
        radians = math.radians(ordinate_angle)
        vector = entity.get_measurement()
        vx, vy = float(vector[0]), float(vector[1])
        nominal = (
            (
                vx * math.cos(radians) + vy * math.sin(radians)
                if dimtype & 64
                else -vx * math.sin(radians) + vy * math.cos(radians)
            )
            * factor
            * scale
        )
        marker = own_reference and any(
            tag.code == 1000 and tag.value == "NEGATIVE_PLACEHOLDER_V1"
            for tag in entity.get_xdata(REFERENCE_DIMENSION_APPID)
        )
        if marker:
            if "-<>" not in raw_text:
                raise ValueError("坐标尺寸文字已改变，无法安全恢复符号")
            raw_text = raw_text.replace("-<>", "<>")
        elif nominal < 0 and "-<>" in raw_text:
            raise ValueError("坐标尺寸文字包含无法判定的负号")
    else:
        nominal = float(entity.get_measurement()) * factor * (1.0 if kind in (2, 5) else scale)
    vertex = None
    if kind in (0, 1):
        first = _xy(entity.dxf.defpoint2, scale)
        second = _xy(entity.dxf.defpoint3, scale)
        location = _xy(entity.dxf.defpoint, scale)
        angle = float(entity.dxf.get("angle", 0))
    elif kind in (3, 4):
        first = _xy(entity.dxf.defpoint, scale)
        second = _xy(entity.dxf.defpoint4, scale)
        location = _xy(entity.dxf.get("text_midpoint", entity.dxf.defpoint4), scale)
        angle = math.degrees(math.atan2(second[1] - first[1], second[0] - first[0]))
    elif kind == 6:
        first = _xy(entity.dxf.defpoint, scale)
        second = _xy(entity.dxf.defpoint2, scale)
        location = _xy(entity.dxf.defpoint3, scale)
        angle = ordinate_angle
    elif kind == 5:
        first = _xy(entity.dxf.defpoint2, scale)
        second = _xy(entity.dxf.defpoint3, scale)
        vertex = _xy(entity.dxf.defpoint4, scale)
        location = _xy(entity.dxf.defpoint, scale)
        angle = 0.0
        if abs(nominal - 180) <= 1e-9:
            direction = (first[0] - vertex[0], first[1] - vertex[1])
            placement = (location[0] - vertex[0], location[1] - vertex[1])
            if direction[0] * placement[1] - direction[1] * placement[0] < 0:
                first, second = second, first
        _check_angular_dimension_graphics(entity, scale, vertex, first, location, nominal)
    else:
        line1_start, line1_end = _xy(entity.dxf.defpoint2, scale), _xy(entity.dxf.defpoint3, scale)
        line2_start, line2_end = _xy(entity.dxf.defpoint4, scale), _xy(entity.dxf.defpoint, scale)
        vertex = _line_intersection(line1_start, line1_end, line2_start, line2_end)
        first = (
            vertex[0] + line1_end[0] - line1_start[0],
            vertex[1] + line1_end[1] - line1_start[1],
        )
        second = (
            vertex[0] + line2_end[0] - line2_start[0],
            vertex[1] + line2_end[1] - line2_start[1],
        )
        location = _xy(entity.dxf.defpoint5, scale)
        angle = 0.0
        _check_angular_dimension_graphics(entity, scale, vertex, first, location, nominal)
    return DetachedDimension(
        uuid4().hex,
        ("ordinate_x" if dimtype & 64 else "ordinate_y")
        if kind == 6
        else {
            0: "rotated",
            1: "aligned",
            2: "angular_2l",
            3: "diameter",
            4: "radius",
            5: "angular_3p",
        }[kind],
        first,
        second,
        location,
        angle,
        nominal,
        tolerance,
        str(entity.dxf.layer),
        precision,
        factor,
        raw_text,
        vertex,
    )


def write_detached_dimension(document: Any, dimension: DetachedDimension) -> str:
    """Create a native DIMENSION with its definition points and tolerance."""
    dx = dimension.second_mm[0] - dimension.first_mm[0]
    dy = dimension.second_mm[1] - dimension.first_mm[1]
    angle = math.degrees(math.atan2(dy, dx)) if dimension.kind == "aligned" else dimension.angle_deg
    radians = math.radians(angle)
    measurement = (
        dimension.nominal
        if dimension.kind in ("angular_3p", "angular_2l")
        else (
            dx * math.cos(radians) + dy * math.sin(radians)
            if dimension.kind == "ordinate_x"
            else -dx * math.sin(radians) + dy * math.cos(radians)
        )
        * dimension.linear_factor
        if dimension.kind in ("ordinate_x", "ordinate_y")
        else math.hypot(dx, dy) * dimension.linear_factor
        if dimension.kind in ("radius", "diameter")
        else abs(dx * math.cos(radians) + dy * math.sin(radians)) * dimension.linear_factor
    )
    if not math.isclose(measurement, dimension.nominal, rel_tol=1e-9, abs_tol=1e-7):
        raise ValueError("独立参考尺寸的名义值与定义点及比例不一致，无法安全导出。")
    tolerance = dimension.tolerance
    if tolerance.mode == "limits":
        try:
            tolerance.limits(dimension.nominal)
        except ValueError as exc:
            raise ValueError("公差极限超出范围") from exc
    if tolerance_values_hidden_by_precision(dimension.nominal, tolerance):
        raise ValueError("公差精度不足，非零偏差将显示为零或不同的上下偏差、极限显示相同")
    override = {
        "dimtol": int(tolerance.mode in ("deviation", "symmetric")),
        "dimlim": int(tolerance.mode == "limits"),
        "dimtp": tolerance.upper_deviation,
        "dimtm": -tolerance.lower_deviation,
        "dimtfac": tolerance.text_factor,
        "dimtdec": tolerance.precision,
        "dimtolj": {"bottom": 0, "middle": 1, "top": 2}[tolerance.alignment],
        "dimdec": dimension.precision,
        "dimadec": dimension.precision,
        "dimzin": 0,
        "dimazin": 0,
        "dimlfac": dimension.linear_factor,
    }
    space = document.modelspace()
    if dimension.kind in ("angular_3p", "angular_2l"):
        if dimension.vertex_mm is None:
            raise ValueError("角度尺寸缺少顶点。")
        if dimension.kind == "angular_3p":
            native = space.add_angular_dim_3p(
                base=dimension.location_mm,
                center=dimension.vertex_mm,
                p1=dimension.first_mm,
                p2=dimension.second_mm,
                text=dimension.text_override or "<>",
                override=override,
                dxfattribs={"layer": dimension.layer_name},
            )
        else:
            native = space.add_angular_dim_2l(
                base=dimension.location_mm,
                line1=(dimension.vertex_mm, dimension.first_mm),
                line2=(dimension.vertex_mm, dimension.second_mm),
                text=dimension.text_override or "<>",
                override=override,
                dxfattribs={"layer": dimension.layer_name},
            )
    elif dimension.kind in ("ordinate_x", "ordinate_y"):
        value_text = dimension.text_override or "<>"
        if dimension.nominal < 0:
            value_text = value_text.replace("<>", "-<>")
        override["dimrnd"] = 10**-dimension.precision
        cosine, sine = math.cos(radians), math.sin(radians)
        local_feature = (
            dimension.first_mm[0] + cosine * dx + sine * dy,
            dimension.first_mm[1] - sine * dx + cosine * dy,
        )
        local_end = (
            cosine * dimension.location_mm[0] + sine * dimension.location_mm[1],
            -sine * dimension.location_mm[0] + cosine * dimension.location_mm[1],
        )
        native = space.add_ordinate_dim(
            feature_location=local_feature,
            offset=(
                local_end[0] - local_feature[0],
                local_end[1] - local_feature[1],
            ),
            dtype=1 if dimension.kind == "ordinate_x" else 0,
            origin=dimension.first_mm,
            rotation=dimension.angle_deg,
            text=value_text,
            override=override,
            dxfattribs={"layer": dimension.layer_name},
        )
    elif dimension.kind in ("radius", "diameter"):
        center = (
            dimension.first_mm
            if dimension.kind == "radius"
            else (
                (dimension.first_mm[0] + dimension.second_mm[0]) / 2,
                (dimension.first_mm[1] + dimension.second_mm[1]) / 2,
            )
        )
        mpoint = dimension.second_mm if dimension.kind == "radius" else dimension.first_mm
        factory = space.add_radius_dim if dimension.kind == "radius" else space.add_diameter_dim
        native = factory(
            center=center,
            mpoint=mpoint,
            text=dimension.text_override or "<>",
            override=override,
            dxfattribs={"layer": dimension.layer_name},
        )
        native.set_location(dimension.location_mm, leader=False)
    elif dimension.kind == "aligned":
        length = math.hypot(dx, dy)
        if length <= 1e-12:
            raise ValueError("对齐参考尺寸的定义点不能重合。")
        distance = (
            (dimension.location_mm[0] - dimension.first_mm[0]) * -dy
            + (dimension.location_mm[1] - dimension.first_mm[1]) * dx
        ) / length
        native = space.add_aligned_dim(
            p1=dimension.first_mm,
            p2=dimension.second_mm,
            distance=distance,
            text=dimension.text_override or "<>",
            override=override,
            dxfattribs={"layer": dimension.layer_name},
        )
    else:
        native = space.add_linear_dim(
            base=dimension.location_mm,
            p1=dimension.first_mm,
            p2=dimension.second_mm,
            angle=dimension.angle_deg,
            text=dimension.text_override or "<>",
            override=override,
            dxfattribs={"layer": dimension.layer_name},
        )
    if dimension.kind == "angular_2l":
        # ezdxf's two-line renderer visits the definition lines in the
        # opposite order to its measurement function. Render with the pairs
        # swapped, then restore the native definition for CAD readers.
        dxf = native.dimension.dxf
        saved = (dxf.defpoint2, dxf.defpoint3, dxf.defpoint4, dxf.defpoint)
        dxf.defpoint2, dxf.defpoint3, dxf.defpoint4, dxf.defpoint = (
            saved[2],
            saved[3],
            saved[0],
            saved[1],
        )
        try:
            renderer = native.render()
        finally:
            dxf.defpoint2, dxf.defpoint3, dxf.defpoint4, dxf.defpoint = saved
    else:
        renderer = native.render()
    if (
        dimension.kind in ("ordinate_x", "ordinate_y")
        and dimension.nominal < 0
        and tolerance.mode == "limits"
    ):
        correct_ordinate_limit_graphics(renderer, dimension.nominal)
    if tolerance.mode == "limits":
        limit_text = dimension.text_override or "<>"
        if limit_text == "<>":
            if dimension.kind in ("radius", "diameter"):
                limit_text = ("R" if dimension.kind == "radius" else "⌀") + "<> mm"
            elif dimension.kind in ("angular_3p", "angular_2l"):
                limit_text = "<>°"
        limit_text = limit_text.replace("\\", "\\\\").replace("{", r"\{").replace("}", r"\}")
        limit_text = re.sub(r"%(?=%)", "%{}", limit_text)
        apply_limit_text_affixes(
            renderer, limit_text, angular=dimension.kind in ("angular_3p", "angular_2l")
        )
    else:
        main_text = dimension.text_override or "<>"
        if main_text == "<>":
            if dimension.kind in ("radius", "diameter"):
                main_text = ("R" if dimension.kind == "radius" else "⌀") + "<> mm"
            elif dimension.kind in ("angular_3p", "angular_2l"):
                main_text = "<>°"
        if dimension.kind in ("ordinate_x", "ordinate_y") and dimension.nominal < 0:
            main_text = main_text.replace("<>", "-<>")
        main_text = main_text.replace("\\", "\\\\").replace("{", r"\{").replace("}", r"\}")
        main_text = re.sub(r"%(?=%)", "%{}", main_text)
        apply_dimension_main_text(
            renderer,
            reference=False,
            kind="angle" if dimension.kind in ("angular_3p", "angular_2l") else dimension.kind,
            template=main_text,
        )
    if dimension.kind in ("angular_3p", "angular_2l") and tolerance.mode != "none":
        clear_angular_tolerance_text(renderer)
    xdata = [(1000, dimension.dimension_id)]
    if dimension.kind in ("ordinate_x", "ordinate_y"):
        xdata.append((1000, f"{ORDINATE_AXIS_SNAPSHOT_PREFIX}{dimension.angle_deg!r}"))
        xdata.append((1000, f"{ORDINATE_TYPE_SNAPSHOT_PREFIX}{dimension.kind}"))
    if (
        dimension.kind in ("ordinate_x", "ordinate_y")
        and dimension.nominal < 0
        and "<>" in (dimension.text_override or "<>")
    ):
        xdata.append((1000, "NEGATIVE_PLACEHOLDER_V1"))
    native.dimension.set_xdata(REFERENCE_DIMENSION_APPID, xdata)
    if dimension.kind == "aligned":
        native.dimension.dxf.dimtype = (int(native.dimension.dxf.dimtype) & ~15) | 1
        native.dimension.dxf.defpoint = (*dimension.location_mm, 0.0)
    return str(native.dimension.dxf.handle)
