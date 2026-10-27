# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Engineering drawing replay upgrades archives without replacing audit history."""

import json
from pathlib import Path
from uuid import uuid4

from mycad.app import build_app, new_document, open_app_document
from mycad.core.persistence import save_document


def test_part_archive_roundtrip_and_old_audit_preserved(tmp_path: Path) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 20, "size_z": 8}, "test")
    old = loaded.document.commands[0]
    assert loaded.document.archive_version == 1
    sheet = uuid4()
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(sheet)}, "test")
    assert loaded.document.archive_version == 3
    loaded.bus.execute(
        "drawing.view.create", {"view_id": str(uuid4()), "sheet_id": str(sheet)}, "test"
    )
    before = services.kernel.drawing_state
    path = tmp_path / "engineering.my3d"
    save_document(loaded.document, path)
    saved = path.read_bytes()
    assert json.loads(saved)["version"] == 3
    reopened = open_app_document(services, path)
    assert path.read_bytes() == saved
    assert services.kernel.drawing_state == before
    assert reopened.document.commands[0] == old
    reopened.bus.undo()
    assert not services.kernel.drawing_state.views
    reopened.bus.redo()
    assert services.kernel.drawing_state == before


def test_annotation_cascade_roundtrip_and_unknown_version(tmp_path: Path) -> None:
    import pytest

    from mycad.core.exceptions import MycadError

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 20, "size_z": 8}, "test")
    sheet, base, child, annotation = (str(uuid4()) for _ in range(4))
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": sheet})
    loaded.bus.execute(
        "drawing.view.create",
        {
            "views": [
                {"view_id": base, "sheet_id": sheet},
                {"view_id": child, "sheet_id": sheet, "parent_id": base, "direction": "left"},
            ]
        },
    )
    loaded.bus.execute(
        "drawing.annotation.create",
        {
            "annotation_id": annotation,
            "view_id": child,
            "kind": "diameter",
            "references": [{"kind": "cylindrical_face", "parameters": {"axis_x": 0.0}}],
            "position_mm": [40, 60],
        },
    )
    state = services.kernel.drawing_state
    path = tmp_path / "drawing.my3d"
    save_document(loaded.document, path)
    reopened = open_app_document(services, path)
    assert services.kernel.drawing_state == state
    reopened.bus.execute("drawing.view.delete", {"view_id": base})
    assert not services.kernel.drawing_state.views
    assert not services.kernel.drawing_state.annotations
    reopened.bus.undo()
    assert services.kernel.drawing_state == state
    payload = json.loads(path.read_text())
    payload["commands"][-1]["version"] = 999
    path.write_text(json.dumps(payload))
    invalid = path.read_bytes()
    with pytest.raises(MycadError):
        open_app_document(services, path)
    assert path.read_bytes() == invalid
    assert services.kernel.drawing_state == state
