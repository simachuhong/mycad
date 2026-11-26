# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Datum pointer styles are protected by a replay version."""

from pathlib import Path

import pytest

from mycad import app
from mycad.core.exceptions import ValidationError
from mycad.core.geometric_tolerance import DatumIdentifier
from mycad.core.persistence import save_document


@pytest.mark.parametrize("style", ["open", "none"])
def test_datum_arrow_style_version_and_history(tmp_path: Path, style: str) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    datum = DatumIdentifier("8" * 32, "A", (10, 10), (0, 0), arrow_style=style)
    params = {"add_datums": [datum.to_mapping()]}
    with pytest.raises(ValidationError, match="箭头"):
        loaded.bus.execute("drawing.tolerance.batch", params, "local", version=28)
    explicit_default = dict(datum.to_mapping(), arrow_style="filled")
    with pytest.raises(ValidationError, match="箭头"):
        loaded.bus.execute(
            "drawing.tolerance.batch", {"add_datums": [explicit_default]}, "local", version=28
        )
    loaded.bus.execute("drawing.tolerance.batch", params, "local", version=29)
    assert services.kernel.drawing_datum_identifiers == (datum,)
    loaded.bus.undo_operation()
    assert not services.kernel.drawing_datum_identifiers
    loaded.bus.redo_operation()
    path = tmp_path / "datum-arrow.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (datum,)
