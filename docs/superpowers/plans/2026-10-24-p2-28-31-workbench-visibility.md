# P2-28–31 Professional Workbench and Visibility Plan

> **For agentic workers:** Implement the tasks in order with a focused failing regression before each behavior change. Keep the existing checkout and do not commit its prior uncommitted Phase 2 work.

**Goal:** Close the professional-workbench and viewport visibility requirements in Phase 2, while keeping the application on its current PySide6 and pyqtgraph/OpenGL stack.

**Architecture:** Retain the five-zone `QMainWindow` and the core → geom → UI boundary. Keep colors explicit at the Qt/GL boundary; pass BREP display data and runtime-only topology IDs through neutral viewport DTOs; keep navigation and selection state in UI memory, outside `Document` and `.mc.json`.

**Tech Stack:** Python 3.12–3.14, PySide6 6.12, pyqtgraph 0.13.7, build123d 0.11.1, existing OCCT adapter, pytest, Ruff, and basedpyright.

**Spec:** `.omo/plans/phase2-agent-loop.md` P2-28–31; `docs/phase2-UI设计方案.md` sections 2, 5, 6, 9, and 10; existing runtime identity contracts in `src/mycad/core/identity.py` and `src/mycad/core/semantic_refs.py`.

## Global Constraints

- `src/mycad/core/*` must not import build123d, OCP, numpy, or PySide6; backend geometry extraction stays in `src/mycad/geom/*`; PySide6/OpenGL stays in `src/mycad/ui/*`.
- Preserve Command Bus as the only model-write path. Camera, theme, selection, and previews are runtime UI state and do not modify `.mc.json` v1.
- Add no runtime dependency and do not replace the current renderer without same-machine evidence that it cannot meet the target.
- Keep Qt colors as QColor/hex/integer colors and GL colors as normalized 0–1 RGBA; always use opaque alpha for the default background.
- Do not expose nonfunctional 2D/sketch tools or Phase 3 AI controls as delivered features; report any acceptance that depends on later geometry work as partial.
- No commit, push, PR, release, or reset of the shared feature workspace.

## Review Focus

- Top-facing faces must receive light; reversed/back-facing faces must not become the default whole-model dark surface.
- BREP boundary lines must not reintroduce triangle diagonals; mesh edges appear only in the diagnostic mode.
- Edge/face/vertex selection IDs must expire after geometry mutation, undo/redo, document replacement, and history-preview changes.
- Screen-space pick tolerance and camera orientation must remain usable at the supported Qt scale factors.
- Empty documents, hidden docks, narrow screens, and unsupported workspace actions must remain clear and operable.

## File Structure

- `src/mycad/ui/theme.py` (new): light/dark semantic colors and application palette application.
- `src/mycad/ui/viewport.py`: GL color contract, lighting shader, BREP/diagnostic line layers, camera, input and selection presentation.
- `src/mycad/ui/main_window.py` and `src/mycad/ui/right_panel.py`: native workbench layout, contextual actions, panel states, and view controls.
- `src/mycad/core/viewport_protocol.py`: immutable, backend-neutral BREP display records and runtime IDs; do not expand `Tessellation` or persistence schema.
- `src/mycad/geom/query.py` and `src/mycad/geom/kernel.py`: extract BREP face/edge/vertex presentation data and invalidate its runtime mappings with geometry revisions.
- `tests/ui/test_viewport.py`, `tests/ui/test_menus_toolbar.py`, new `tests/ui/test_theme.py`, `tests/core/test_viewport_protocol.py`, and `tests/geom/test_viewport_snapshots.py`: scoped behavior checks.
- `.omo/evidence/task-P2-28-phase2-agent-loop.md` through `task-P2-31-phase2-agent-loop.md`, `.omo/plans/phase2-agent-loop.md`, and `.omo/start-work/ledger.jsonl`: evidence and truthful task status.

## Tasks

### Task 1: P2-28 — light workspace and correct viewport lighting

**Files:** Modify `src/mycad/ui/viewport.py`, `tests/ui/test_viewport.py`, `.omo/plans/phase2-agent-loop.md`; create/update P2-28 evidence and the real-render capture under `.omo/evidence/phase2-foundation/`.

**Interfaces:** `VIEWPORT_BACKGROUND` remains the opaque `#EFF3F7`; `SHADED_COLOR`, `EDGE_COLOR`, and `HIGHLIGHT_COLOR` remain GL-normalized tuples. Add cached `build_workbench_shader() -> ShaderProgram`, with a top-facing light and a fill term, and use it for body and selection meshes.

- [x] Add a regression that inspects the shader used by `GLViewport` and verifies a positive-Z key-light component, a fill coefficient of at least `0.4`, and unchanged opaque body/edge GL color inputs; keep the current translucent selection accent unchanged. Verify the regression fails against pyqtgraph's current back-facing `shaded` shader.
- [x] Implement `build_workbench_shader()` from the locked pyqtgraph shader primitives; pass the world-space `(0.35, -0.25, 0.90)` key-light direction, keep normals in world coordinates, and normalize the direction in the fragment shader; use `0.45 + 0.55 * max(dot(normal, light), 0)` diffuse/fill response, preserve opaque scene rendering, and keep color-range conversion at call sites.
- [x] Capture and inspect the same flange, thin plate, cylinder, and empty-document cases on the available Intel/Mesa X11 display; record driver, renderer, screenshot, background pixel, top-face sample, and limitations.
- [x] Run `tests/ui/test_viewport.py` plus scoped Ruff/format/basedpyright and record P2-28 evidence. Keep P2-28 partial until the selection/picking criteria are met.

### Task 2: P2-29 — native workbench theme and information layout

**Files:** Create `src/mycad/ui/theme.py` and `tests/ui/test_theme.py`; modify `src/mycad/ui/main_window.py`, `src/mycad/ui/right_panel.py`, `tests/ui/test_menus_toolbar.py`; create P2-29 evidence.

**Interfaces:** `ThemeName = Literal["light", "dark"]`; `apply_theme(app: QApplication, theme: ThemeName) -> None`. The default is light. Theme changes affect only application/widget presentation. Preserve the existing five-zone shell, QSettings layout compatibility, menu QAction reuse, and current command-dispatch path.

- [x] Add theme tests for exact canvas/panel/text/focus/error colors, readable text contrast, and a real widget's resulting palette; verify the default currently fails the intended workbench palette check.
- [x] Implement the semantic theme tokens and light/dark `QPalette`; style tabs, dock headers, toolbar, focus, disabled state, and error state using the existing Qt widgets.
- [x] Add a persisted theme selector, named dock-collapse actions, a layout-reset action, and context actions that reveal the existing CLI/plan panel only when requested; do not add new AI or unimplemented 2D/sketch actions.
- [x] Give current file/history/view/modeling actions concise visible labels, platform-independent standard icons where available, shortcut hints in tooltips, and a layout-reset shortcut; preserve visible keyboard focus and explain disabled actions; do not create actions whose backing behavior does not exist.
- [x] Add regressions for default light theme, theme switching, closed-bottom-panel startup, CLI/plan reveal, layout reset, and QSettings round-trip.
- [x] Inspect the empty-document, current 3D, selected-feature, plan-confirmation, and error-recovery views at 1920×1080 and 1366×768, plus available 100%, 125%, 150%, and 200% scale settings; record each tested combination and the 1920×1080 viewport share. P2-29 remains partial until functional drawing/sketch screens from P2-32+ exist.

### Task 3: P2-30 — BREP boundaries and explicit render modes

**Files:** Modify `src/mycad/core/viewport_protocol.py`, `src/mycad/geom/query.py`, `src/mycad/geom/kernel.py`, `src/mycad/ui/viewport.py`, `src/mycad/ui/main_window.py`, and their core/geom/UI viewport tests; create P2-30 evidence.

**Interfaces:** Define `Point3 = tuple[float, float, float]` in `core.viewport_protocol`. Add frozen `ViewportBoundaryEdge(topology_id: TopologyId, body_id: BodyId, points: tuple[Point3, ...])` and `boundary_edges: tuple[ViewportBoundaryEdge, ...] = ()` to `ViewportData`. These IDs are runtime-only and invalidated with the current geometry revision. Add `RenderMode = Literal["shaded", "shaded-edges", "engineering-wireframe", "mesh-diagnostic"]` and `GLViewport.set_render_mode(mode: RenderMode) -> None`; default to `shaded-edges`. Do not change `Tessellation` fields.

- [x] Add DTO validation tests and geometry tests proving boundary polylines follow BREP edges, have current topology/body identities, are stable on repeated reads of one revision, and expire after replay or document replacement.
- [x] Implement BREP edge sampling in `geom/query.py` from oriented build123d edges; build the neutral DTO in `BuildKernel` and cache it with the same revision/tolerance rules as the mesh.
- [x] Add viewport tests showing shaded mode has no line layer, shaded-edges uses only BREP boundaries, wireframe hides faces, and mesh-diagnostic alone draws triangle edges.
- [x] Implement `set_render_mode()` and connect a checkable view-mode action group without changing selection or document history.
- [x] Capture flat, curved, holed, filleted, and thin geometry in each mode; verify flat faces have no triangle diagonals, circular outlines and hole walls remain distinct, sharp edges are preserved, lines do not remain after undo/redo, and selection highlights do not obscure geometry. Compare extraction/render cost against P2-09. Run scoped core/geom/UI tests and record P2-30 evidence.

### Task 4: P2-31 — standard navigation and explicit selection state

**Files:** Modify `src/mycad/core/viewport_protocol.py`, `src/mycad/geom/query.py`, `src/mycad/geom/kernel.py`, `src/mycad/ui/viewport.py`, `src/mycad/ui/main_window.py`, `src/mycad/ui/right_panel.py`, and their focused tests; create P2-31 evidence.

**Interfaces:** Add frozen `ViewportVertex(topology_id: TopologyId, body_id: BodyId, point: Point3)` and `ViewportFace(topology_id: TopologyId, body_id: BodyId)` to `core.viewport_protocol`. Extend `ViewportData` with `vertices`, unique `faces`, `triangle_face_ids` (one per mesh triangle), and `triangle_body_ids` (one per mesh triangle). Validate both parallel triangle-ID arrays against the mesh triangle count. Add `ViewOrientation = Literal["front", "back", "left", "right", "top", "bottom", "isometric"]`, `ProjectionMode = Literal["orthographic", "perspective"]`, `SelectionKind = Literal["body", "face", "edge", "vertex"]`, and UI-only frozen `SelectionState(geometry_revision: int, kind: SelectionKind, body_ids: tuple[BodyId, ...], topology_ids: tuple[TopologyId, ...])`. `GLViewport.set_orientation(orientation: ViewOrientation) -> None`, `GLViewport.set_projection_mode(mode: ProjectionMode) -> None`, `GLViewport.set_selection_filter(kind: SelectionKind) -> None`, and `GLViewport.selection() -> SelectionState | None` expose camera and selection state. Use front/back from ±Y, left/right from ±X, top/bottom from ±Z, and isometric from (+X,+Y,+Z); default projection is orthographic. Selection is cleared when the binding or geometry revision changes.

- [x] Add pure camera mapping tests for all seven orientations and the two projection modes, including stable camera center and distance.
- [x] Add viewport-data mapping for exact BREP faces and vertices plus triangle-to-face IDs; verify all IDs are runtime-only and stale IDs cannot be reselected after a revision change.
- [x] Add selection tests for body/face/edge/vertex filters, hover preselection, click selection, Ctrl toggling within one filter, left-to-right containment and right-to-left crossing selection, Escape cancellation without model change, history-preview isolation, and a 6 logical-pixel screen-space pick radius independent of zoom.
- [x] Connect standard-view, projection, coordinate/grid, selection-filter, and return-current controls; expose global XYZ and the active XY guide grid as view-only state, synchronize selection identity with the right panel, and keep all these actions outside `Document`.
- [ ] Implement drawing/edit preview and explicit modeling confirmation once the P2-32+ geometry workflows exist; meanwhile verify selection leaves document revision and Bus history unchanged. Inspect the supported 3D desktop interactions and record P2-31 evidence; keep this task partial for unsupported operations.

## Verification and status rules

- Per task, run its scoped tests, Ruff check/format, and basedpyright for touched paths; run the full suite only at the project’s final integration gate.
- Verify the runtime DTO still passes `tests/test_layering.py`; run no tests for unsupported behavior solely to increase coverage.
- Use `git diff --check`, inspect screenshots/links, and validate the ledger JSONL after appending diagnostics.
- Keep P2-28–31 unchecked or partial wherever real desktop, scale-factor, unsupported-workspace, stale-topology, or confirmed-interaction acceptance remains unproven.
- Do not mark all of F complete merely because the color or offscreen scene-graph tests pass.

## 2026-10-25 用户确认的范围调整与收口

用户选择 F 三维工作台先收口、真实二维/草图随 G 联验，取代 Task 2/4 原因 G 依赖而保持整体 partial 的约定。Task 4 中三维建模预览/确认已完成并验证；二维 drawing/edit 子项仍待 G，不勾选为已交付。P2-29/P2-31 按该范围工程收口，P2-28/P2-30 联合回归。证据、297 项范围回归、8 组高 DPI 与原生桌面检查、人工待验清单见 [F 收口记录](../../../.omo/evidence/task-P2-F-closure.md)。
