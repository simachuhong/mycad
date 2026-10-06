# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Static-failure expectations for PlannedCommand's AffectedObject gate.

basedpyright scans this directory; pytest never collects it (the file name
does not match ``test_*.py``). The eight assignments below must type-check
without any ignore directive; the final line must be flagged — the
spec-mandated ignore pins that expected diagnostic, so removing the
argument error (or the gate) breaks the build either way.
"""

from mycad.core.document import PlannedCommand

_box = PlannedCommand("feature.box", 1, {}, "Create a box.", "box_body")
_cylinder = PlannedCommand("feature.cylinder", 1, {}, "Create a cylinder.", "cylinder_body")
_extrude = PlannedCommand("feature.extrude", 1, {}, "Extrude a profile.", "extruded_body")
_revolve = PlannedCommand("feature.revolve", 1, {}, "Revolve a profile.", "revolved_body")
_hole = PlannedCommand("feature.hole", 1, {}, "Cut a hole.", "hole")
_hole_pattern = PlannedCommand("feature.hole_pattern", 1, {}, "Pattern holes.", "hole_pattern")
_fillet = PlannedCommand("modify.fillet", 1, {}, "Fillet edges.", "edge")
_boolean_cut = PlannedCommand("modify.boolean_cut", 1, {}, "Boolean cut.", "tool_body")

PlannedCommand("feature.box", 1, {}, "", "bogus")  # pyright: ignore[reportArgumentType]
