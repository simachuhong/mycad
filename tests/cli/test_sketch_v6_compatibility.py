# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Adding associated sketches must not invalidate existing CLI sketch scripts."""

from pathlib import Path
from uuid import uuid4

from mycad import app
from mycad.cli.session import CliSession
from mycad.commands.grammar import to_cli
from mycad.core.sketch import CircleEntity, Sketch, WorkPlaneFrame


def test_legacy_sketch_cli_roundtrip_validation_and_execution(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (CircleEntity(uuid4().hex, (0, 0), 5),))
    line = to_cli("sketch.create", sketch.to_mapping(version=3), services.registry)
    script = tmp_path / "sketch.txt"
    script.write_text(line + "\n", encoding="utf-8")
    session = CliSession(services)
    assert session.validate_file(script) == 0
    assert session.run_script(script) == 0
    assert services.kernel.sketches[0].sketch_id == sketch.sketch_id
