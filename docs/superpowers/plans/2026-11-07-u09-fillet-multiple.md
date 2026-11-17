# U09 FILLET Multiple Implementation Plan

**Goal:** Make FILLET finish after one successful operation unless Multiple is selected.

**Architecture:** Canvas tracks command-scoped multiple mode. Draft operations finish synchronously; saved-source operations finish only after the existing mixed-edit candidate succeeds. Enter at the initial prompt exits; a subsequent Enter repeats the last command.

**Spec:** Autodesk 2026 `To Work With 2D Fillets and Rounds` and `To Fillet Multiple Sets of Objects`; existing video reference does not show this option.

## Constraints and review focus

- A failed geometry or asynchronous candidate must leave FILLET available for retry.
- Multiple applies to draft, no-trim polyline and saved-source candidate operations.
- Undo inside the command remains available in Multiple mode; draft undo is unchanged.
- Switching tools or restarting FILLET resets Multiple; radius and trim settings persist.
- Enter and Esc must not silently commit an unfinished first-object or option selection.

## Tasks

- [ ] Add failing tests for single completion, repeated Multiple operations, Enter exit and command repeat.
- [ ] Implement command state for synchronous and saved-source candidate completion.
- [ ] Verify failure/retry, draft undo, saved-source preview and existing FILLET windows.
