# Contextual Modeling Interaction Implementation Plan

> 2026-10-25：对应交互设计已因用户体验反馈暂停。本计划仅保留实施历史，
> 不继续据此扩展参数面板。后续依据 [Solid Edge 鼠标操作研究](../../design/solid-edge-mouse-interaction-study.md)
> 制定替代设计。

> **For agentic workers:** Work in the shared checkout. Preserve all
> pre-existing user changes; do not reset, commit, or run the full suite.

**Goal:** Make modeling operations selection-driven and edit their parameters in
a non-modal floating panel that keeps the viewport interactive.

**Design:** `docs/superpowers/specs/2026-10-24-contextual-modeling-interaction.md`

## Steps

1. Extend the geometry selector resolver with optional geometric anchors and
   let `BuildKernel` translate live face/edge topology IDs into replayable,
   neutral selector mappings. Keep runtime IDs out of command parameters.
2. Add command-schema variants for anchor-aware Hole faces and Fillet edges;
   preserve existing unanchored descriptors and named-group archive forms.
3. Embed the parameter editor as a compact child panel in the viewport, with a
   custom header and no operating-system title bar. Show a small prompt before
   the required pick; reveal dimensions, Preview, Apply, and Cancel afterward.
4. Wire Hole/Fillet into face/edge selection and Box/Extrude into XY work-plane
   point placement. Right-click repositions the active panel and Escape cancels
   the tool. Restore the previous selection filter after cancel or apply.
5. Run scoped lint/type checks and launch the GUI for manual review. Do not run
   automated tests unless the user requests them.

## Acceptance reminders

- Preview must not mutate active kernel, Document, Bus, or Plan state.
- Stale async previews are ignored after a new selection, new edit, cancel,
  document replacement, or execution start.
- Right-click is an editor affordance; only “应用并执行” submits the plan.
- Every selector generated from a pick must resolve to exactly the picked
  geometry after deterministic replay.
