# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Statistical reporting contracts for the Phase 2 benchmark runner."""

from __future__ import annotations

import pytest

from mycad.benchmarks import summarize_samples


def test_summarize_samples_reports_nearest_rank_percentiles() -> None:
    summary = summarize_samples([1.0, 2.0, 3.0, 4.0])

    assert summary == {
        "count": 4,
        "p50_ms": 2.0,
        "p95_ms": 4.0,
        "max_ms": 4.0,
        "p95_note": "small_sample",
    }


def test_summarize_samples_requires_at_least_one_measurement() -> None:
    with pytest.raises(ValueError, match="at least one"):
        summarize_samples([])
