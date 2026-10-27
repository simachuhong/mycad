# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Neutral measurement request and result contracts."""

from __future__ import annotations

from mycad.core.measurements import MeasurementRequest, MeasurementResult


def test_measurement_request_keeps_neutral_reference_and_revision() -> None:
    request = MeasurementRequest(kind="body_volume", revision=4)

    assert request.kind == "body_volume"
    assert request.references == ()
    assert request.revision == 4


def test_measurement_result_identifies_value_unit_source_and_revision() -> None:
    result = MeasurementResult(
        value=120.0,
        unit="mm",
        revision=4,
        description="Cylindrical face diameter",
    )

    assert result.value == 120.0
    assert result.unit == "mm"
    assert result.revision == 4
    assert result.source == "BREP"
    assert result.error is None


def test_measurement_result_can_explain_unsupported_selection() -> None:
    result = MeasurementResult(
        value=None,
        unit="mm",
        revision=4,
        description="Circular edge center distance",
        error="Select two circular edges.",
    )

    assert result.value is None
    assert result.error == "Select two circular edges."
