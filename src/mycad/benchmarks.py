# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Small, deterministic statistics used by published benchmark reports."""

from __future__ import annotations

from math import ceil, isfinite
from typing import TypedDict


class SampleSummary(TypedDict):
    """Distribution summary that preserves whether the tail has enough data."""

    count: int
    p50_ms: float
    p95_ms: float
    max_ms: float
    p95_note: str | None


def summarize_samples(samples_ms: list[float]) -> SampleSummary:
    """Summarize wall-clock samples with nearest-rank P50/P95.

    Nearest-rank is ``sorted_samples[ceil(p * n) - 1]``. Fewer than 30
    observations still produce an empirical P95 for inspection, but tag it
    ``small_sample`` so it cannot be mistaken for a stable tail estimate.
    """
    if not samples_ms:
        raise ValueError("at least one measurement is required")
    if any(not isfinite(sample) or sample < 0 for sample in samples_ms):
        raise ValueError("measurements must be finite and non-negative")

    ordered = sorted(samples_ms)
    p50_rank = max(1, ceil(0.50 * len(ordered)))
    p95_rank = max(1, ceil(0.95 * len(ordered)))
    return {
        "count": len(ordered),
        "p50_ms": ordered[p50_rank - 1],
        "p95_ms": ordered[p95_rank - 1],
        "max_ms": ordered[-1],
        "p95_note": "small_sample" if len(ordered) < 30 else None,
    }
