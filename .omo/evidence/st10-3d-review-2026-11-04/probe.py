"""Read-only product review: reproduce draft interaction gaps in temporary documents.

Run from repository root with QT_QPA_PLATFORM=offscreen uv run python <this file>.
Uses internal display state as a diagnostic, not as desktop acceptance evidence.
"""

import hashlib
import json
from pathlib import Path

from PySide6.QtWidgets import QApplication

from mycad import app
from mycad.ui.part_sketch_workbench import PartSketchWorkbench
from mycad.ui.viewport import GLViewport


def make_task():
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    view.show()
    QApplication.processEvents()
    task = PartSketchWorkbench(services, loaded, view, session_identity=1)
    task.lock_plane()
    task.object_snap.setChecked(False)
    return services, loaded, view, task


qapp = QApplication([])
report = {}
services, loaded, view, task = make_task()
task.select_tool("line")
task.place_uv((0.0, 0.0))
task._preview_drawing((10.0, 0.05))
preview_end = task._rubber_band_curve[-1]
task.place_uv((10.0, 0.05), numeric=False)
entity = task.session.sketch.entities[0]
report["preview_vs_inferred_commit"] = {
    "preview_world_end": preview_end,
    "accepted_entity": entity.to_mapping() if hasattr(entity, "to_mapping") else repr(entity),
    "accepted_relations": [r.kind for r in task.session.sketch.constraints],
    "accepted_world_end": task.session.sketch.frame.local_to_world(entity.end_mm),
}
task.reject()
view.close()

services, loaded, view, task = make_task()
task.select_tool("rectangle")
task.place_uv((0.0, 0.0))
task.place_uv((40.0, 30.0))
task.select_tool("line")
task.place_uv((50.0, 0.0))
task._preview_drawing((60.0, 10.0))
pending_before = len(task._points)
task.preview()
enabled = task.confirm_button.isEnabled()
task.confirm()
report["finish_with_pending_geometry"] = {
    "pending_point_count_before_preview": pending_before,
    "confirmation_enabled": enabled,
    "committed_command_count": len(loaded.document.commands),
    "committed_entity_count": len(services.kernel.sketches[0].entities),
    "task_finished": task._finished,
}
view.close()

services, loaded, view, task = make_task()
task.select_tool("line")
task.place_uv((0.0, 0.0))
task.place_uv((10.0, 0.0))
task.select_tool("rectangle")
task.place_uv((20.0, 0.0))
task._preview_drawing((30.0, 10.0))
task.undo()
report["undo_during_pending_geometry"] = {
    "accepted_entity_count": len(task.session.sketch.entities),
    "pending_point_count": len(task._points),
    "temporary_curve_point_count": len(task._rubber_band_curve),
    "displayed_curve_count": view.draft_sketch_curve_count(),
}
task.reject()
view.close()

report["source_sha256"] = {
    name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
    for name in (
        "src/mycad/ui/part_sketch_workbench.py",
        "src/mycad/ui/main_window.py",
        "src/mycad/ui/viewport.py",
        "src/mycad/builtin_commands/specs.py",
        "src/mycad/builtin_commands/datum_specs.py",
    )
}
output = json.dumps(report, ensure_ascii=False, indent=2)
Path(__file__).with_name("probe-results.json").write_text(output + "\n", encoding="utf-8")
print(output)
