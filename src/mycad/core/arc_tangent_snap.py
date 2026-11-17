# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Tangent contacts for an arc defined by two preceding points."""

from __future__ import annotations

import math

from mycad.core.sketch import Point2D


def tangent_endpoints_to_line(
    first: Point2D, second: Point2D, line_start: Point2D, line_end: Point2D
) -> tuple[Point2D, ...]:
    """Find finite-line contacts of circles passing through two given points."""
    dx, dy = second[0] - first[0], second[1] - first[1]
    chord = math.hypot(dx, dy)
    lx, ly = line_end[0] - line_start[0], line_end[1] - line_start[1]
    line_length = math.hypot(lx, ly)
    if (
        not math.isfinite(chord)
        or not math.isfinite(line_length)
        or min(chord, line_length) <= 1e-12
    ):
        return ()
    mid = (first[0] + dx / 2, first[1] + dy / 2)
    nx, ny = -dy / chord, dx / chord
    ux, uy = lx / line_length, ly / line_length
    vx, vy = -uy, ux
    height = (mid[0] - line_start[0]) * vx + (mid[1] - line_start[1]) * vy
    dot = nx * vx + ny * vy
    scale = max(chord / 2, abs(height))
    h, half = height / scale, chord / (2 * scale)
    a, b, c = 1 - dot * dot, -2 * h * dot, half * half - h * h
    if abs(a) <= 1e-14:
        roots = () if abs(b) <= 1e-14 else (-c / b,)
    else:
        discriminant = b * b - 4 * a * c
        if discriminant < 0:
            return ()
        root = math.sqrt(discriminant)
        q = -(b + math.copysign(root, b)) / 2
        roots = (-b / (2 * a),) if q == 0 else (q / a, c / q)
    contacts: list[Point2D] = []
    for value in roots:
        offset = value * scale
        center = (mid[0] + offset * nx, mid[1] + offset * ny)
        if not all(math.isfinite(coordinate) for coordinate in center):
            continue
        signed_distance = (center[0] - line_start[0]) * vx + (center[1] - line_start[1]) * vy
        point = (center[0] - signed_distance * vx, center[1] - signed_distance * vy)
        along = (point[0] - line_start[0]) * ux + (point[1] - line_start[1]) * uy
        if not 0 <= along <= line_length:
            continue
        tolerance = max(1e-12, chord * 1e-12)
        if math.dist(first, point) <= tolerance or math.dist(second, point) <= tolerance:
            continue
        offset_x, offset_y = point[0] - first[0], point[1] - first[1]
        if abs((dx / chord) * offset_y - (dy / chord) * offset_x) <= tolerance:
            continue
        if point not in contacts:
            contacts.append(point)
    return tuple(contacts)


def tangent_endpoints_to_circle(
    first: Point2D, second: Point2D, target_center: Point2D, target_radius: float
) -> tuple[Point2D, ...]:
    """Find contacts on a circle of circles passing through two given points."""
    dx, dy = second[0] - first[0], second[1] - first[1]
    chord = math.hypot(dx, dy)
    if (
        not math.isfinite(chord)
        or chord <= 1e-12
        or not math.isfinite(target_radius)
        or target_radius <= 0
    ):
        return ()
    midpoint = (first[0] + dx / 2, first[1] + dy / 2)
    nx, ny = -dy / chord, dx / chord
    wx, wy = midpoint[0] - target_center[0], midpoint[1] - target_center[1]
    distance = math.hypot(wx, wy)
    if not math.isfinite(distance):
        return ()
    scale = max(chord / 2, distance, target_radius)
    x, y, half, radius = wx / scale, wy / scale, chord / (2 * scale), target_radius / scale
    constant = x * x + y * y - half * half - radius * radius
    linear = 2 * (nx * x + ny * y)
    a = linear * linear - 4 * radius * radius
    b = 2 * constant * linear
    c = constant * constant - 4 * radius * radius * half * half
    if abs(a) <= 1e-14:
        roots = () if abs(b) <= 1e-14 else (-c / b,)
    else:
        # Algebraically equivalent to b² - 4ac, without subtracting nearly
        # equal large terms when the target circle is tiny relative to the arc.
        discriminant = 16 * radius * radius * (constant * constant + half * half * a)
        if discriminant < 0:
            return ()
        root = math.sqrt(discriminant)
        q = -(b + math.copysign(root, b)) / 2
        roots = (-b / (2 * a),) if q == 0 else (q / a, c / q)
    contacts: list[Point2D] = []
    for value in roots:
        center = (midpoint[0] + value * scale * nx, midpoint[1] + value * scale * ny)
        cx, cy = center[0] - target_center[0], center[1] - target_center[1]
        center_distance = math.hypot(cx, cy)
        if not math.isfinite(center_distance) or center_distance <= 1e-12:
            continue
        new_radius = math.dist(center, first)
        for sign in (-1, 1):
            point = (
                target_center[0] + sign * target_radius * cx / center_distance,
                target_center[1] + sign * target_radius * cy / center_distance,
            )
            tolerance = max(1e-12, scale * 1e-12)
            if not math.isclose(
                math.dist(center, point), new_radius, rel_tol=1e-9, abs_tol=tolerance
            ):
                continue
            if math.dist(first, point) <= tolerance or math.dist(second, point) <= tolerance:
                continue
            offset_x, offset_y = point[0] - first[0], point[1] - first[1]
            if abs((dx / chord) * offset_y - (dy / chord) * offset_x) <= tolerance:
                continue
            if not any(math.dist(point, existing) <= tolerance for existing in contacts):
                contacts.append(point)
    return tuple(contacts)
