# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""DXF represents and restores the chosen datum pointer style."""

from pathlib import Path
from typing import Any, cast

import ezdxf.filemanagement
import pytest

from mycad.core.geometric_tolerance import DatumIdentifier
from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketches_dxf


@pytest.mark.parametrize("style", ["filled", "open", "none"])
def test_datum_arrow_style_native_dxf_roundtrip(tmp_path: Path, style: str) -> None:
    datum = DatumIdentifier(
        "8" * 32, "A", (10, 10), (0, 0), layout_mode="shared", arrow_style=style
    )
    path = tmp_path / "datum.dxf"
    report = write_sketches_dxf((), path, datum_identifiers=(datum,))
    assert any("旧版可能无法恢复结构化基准" in warning for warning in report.warnings) == (
        style != "filled"
    )
    document = cast("Any", ezdxf.filemanagement).readfile(path)
    insert = next(iter(document.modelspace().query("INSERT")))
    block = document.blocks.get(insert.dxf.name)
    kinds = [entity.dxftype() for entity in block]
    assert kinds.count("SOLID") == (1 if style == "filled" else 0)
    assert kinds.count("LINE") == (8 if style == "open" else 5)
    imported = read_sketch_dxf(path)
    assert imported.datum_identifiers == (datum,)


def test_open_datum_arrow_with_bent_leader_roundtrips(tmp_path: Path) -> None:
    datum = DatumIdentifier(
        "9" * 32,
        "A",
        (10, 10),
        (0, 0),
        leader_offsets=((-2, -8),),
        layout_mode="shared",
        arrow_style="open",
    )
    path = tmp_path / "bent.dxf"
    write_sketches_dxf((), path, datum_identifiers=(datum,))
    imported = read_sketch_dxf(path)
    assert imported.datum_identifiers == (datum,)
    assert imported.block_definitions == () and imported.block_instances == ()
