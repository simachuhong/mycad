# Contextual Modeling Interaction Design

> 2026-10-25：用户人工体验后否定了当前交互路线。本文保留为历史记录，
> 暂停作为后续实现基线。先完成 [Solid Edge 鼠标操作研究](../../design/solid-edge-mouse-interaction-study.md)，
> 再制定替代设计；尤其重新审视面板遮挡、右键职责、连续选取和动态预览。

## Problem

The current command activation opens a blocking parameter dialog. It takes
focus away from the model, while viewport picks are not connected to feature
parameters. CAD operations should begin from the geometry selection and keep
the viewport available while the user edits dimensions.

## Goal

Use a selection-driven modeling flow with a compact parameter panel embedded
inside the viewport. Hole and fillet begin by selecting a face or edge. Box and
extrude begin by placing their center on the global XY work plane. The panel
appears beside the pointer, stays inside the viewport, and leaves camera and
selection input available. Preview remains temporary and Apply remains an
explicit confirmed command submission.

## Interaction

1. Activating Hole arms face selection; activating Fillet arms edge selection.
   A compact in-viewport prompt explains what to select. A viewport pick fills
   the command's selector and expands the parameter panel at the pointer.
2. Activating Box or Extrude shows a placement prompt. A viewport click places
   the box center or profile center on the global XY work plane, then opens the
   dimensions panel at the pointer. Initial dimensions are usable values that
   the user can change before previewing.
3. The panel is a non-modal child of the viewport, without an operating-system
   title bar. The user can orbit, zoom, pick geometry, or return to the panel
   without dismissing it. Right-clicking the viewport while a command is active
   repositions the panel there.
4. Geometry selectors carry deterministic geometric anchors in command
   parameters. They are regenerated from current runtime topology IDs in the
   geometry adapter and are replayable through the existing command bus.
   Runtime topology IDs themselves never enter a Plan or archive.
5. Preview evaluates committed history plus the candidate command on an
   isolated scratch kernel. It must not mutate the active Document, kernel,
   Bus, or history. Parameter edits clear the stale preview; the Preview button
   calculates the current values.
6. “应用并执行” validates the form, stores parameters in the active Plan,
   and submits through the existing GUI confirmation and CommandBus path.
   Cancel/Escape clears preview and abandons the draft without changing the
   active model. The viewport returns to its previous selection filter.

## Scope and constraints

- Toolbar and command-palette activation share the same contextual workflow.
- Keep geometry-selector conversion inside `mycad.geom`/the `mycad.app`
  composition boundary. `mycad.ui` consumes only neutral selector mappings
  and `ViewportData`.
- Add anchor-aware selector variants for interactive Hole/Fillet parameters;
  keep existing unanchored selectors and named-group wire forms compatible.
- Only the current picked face/edge identity can be converted. Reject stale or
  unsupported topology with a visible actionable message.
- A right-click only opens/repositions the editor. Apply is the sole command
  commit action, preserving the existing user confirmation boundary.
- Every asynchronous preview is guarded by document session and operation
  generation. A stale completion cannot replace a newer preview.

## Acceptance

- Hole/Fillet activate into a visible face/edge selection prompt without a
  blocking dialog; selecting valid geometry fills the selector and opens the
  editor at the pointer.
- Box/Extrude show a placement prompt, accept an XY work-plane click, and then
  show the same in-viewport editor with the picked center filled in.
- The editor has no separate top-level window frame and never disables camera
  controls or viewport selection.
- Right-click with an active operation raises/repositions its editor; Escape
  cancels the operation.
- Preview shows a candidate or a specific actionable error and never changes
  active model state.
- Apply executes once through the existing Plan/CommandBus confirmation path;
  cancel leaves revision, history, active kernel, and archive unchanged.
