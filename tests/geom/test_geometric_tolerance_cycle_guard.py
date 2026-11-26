# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Bound the cost of ambiguous curve point identity checks."""

from collections.abc import Callable, Sequence
from typing import cast

from mycad.geom import kernel

_check = cast(
    "Callable[[tuple[tuple[float, float], ...], tuple[tuple[float, float], ...], Sequence[int]], bool]",
    vars(kernel)["_translated_curve_cycle_may_retarget"],
)
_check_pair = cast(
    "Callable[[tuple[tuple[float, float], ...], tuple[tuple[float, float], ...], Sequence[int]], bool]",
    vars(kernel)["_translated_curve_pair_swap_may_retarget"],
)


def test_large_curve_allows_uniform_translation_but_rejects_unprovable_deformation() -> None:
    before = tuple((float(index), float(index % 5)) for index in range(450))
    translated = tuple((x + 3, y + 4) for x, y in before)
    assert not _check(before, translated, range(len(before)))
    deformed = (*translated[:-1], (translated[-1][0], translated[-1][1] + 1))
    assert _check(before, deformed, range(len(before)))


def test_ambiguous_duplicate_points_reject_multi_point_deformation() -> None:
    before = ((0.0, 0.0), (2.0, 0.0), (0.0, 0.0), (4.0, 1.0))
    after = ((1.0, 1.0), (3.0, 2.0), (0.0, 0.0), (4.0, 1.0))
    assert _check(before, after, (0,))


def test_unrelated_duplicate_points_do_not_block_unambiguous_attached_vertex() -> None:
    before = ((0.0, 0.0), (2.0, 0.0), (4.0, 1.0), (4.0, 1.0), (8.0, 3.0))
    after = ((0.0, 0.0), (3.0, 2.0), (4.0, 1.0), (4.0, 1.0), (9.0, 5.0))
    assert not _check(before, after, (0,))


def test_cycle_is_detected_when_an_unattached_cycle_point_is_duplicated() -> None:
    before = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (10.0, 10.0), (30.0, 10.0))
    after = ((13.0, 4.0), (13.0, 14.0), (3.0, 4.0), (12.0, 19.0), (36.0, 18.0))
    assert _check(before, after, (0,))


def test_four_point_cycle_with_other_deformation_is_detected() -> None:
    before = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (20.0, 10.0), (30.0, 10.0))
    after = ((13.0, 4.0), (13.0, 14.0), (23.0, 14.0), (3.0, 4.0), (36.0, 18.0))
    assert _check(before, after, (0,))


def test_five_point_cycle_with_other_deformation_is_detected() -> None:
    before = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (20.0, 10.0), (30.0, 10.0), (40.0, 7.0))
    after = ((13.0, 4.0), (13.0, 14.0), (23.0, 14.0), (33.0, 14.0), (3.0, 4.0), (46.0, 15.0))
    assert _check(before, after, (0,))


def test_cycle_detects_near_equal_points_across_rounding_boundary() -> None:
    before = ((0.00000000049, 0.0), (10.0, 0.0), (10.0, 10.0), (30.0, 10.0))
    after = ((13.0, 4.0), (13.0, 14.0), (3.00000000051, 4.0), (36.0, 18.0))
    assert _check(before, after, (0,))


def test_pair_swap_detects_near_equal_sums_across_rounding_boundary() -> None:
    before = ((0.00000000049, 0.0), (10.0, 0.0), (20.0, 10.0))
    after = ((13.0, 4.0), (3.00000000051, 4.0), (25.0, 18.0))
    assert _check_pair(before, after, (0,))


def test_pair_swap_does_not_match_sums_outside_tolerance() -> None:
    before = ((0.0, 0.0), (10.0, 0.0), (20.0, 10.0))
    after = ((13.0, 4.0), (3.0000000011, 4.0), (25.0, 18.0))
    assert not _check_pair(before, after, (0,))


def test_pair_swap_bounds_ambiguous_duplicate_candidates() -> None:
    before = ((0.0, 0.0),) * 450
    after = ((1.0, 1.0),) * 449 + ((2.0, 2.0),)
    assert _check_pair(before, after, range(len(before)))
    assert not _check_pair(before, ((1.0, 1.0),) * 450, range(len(before)))
