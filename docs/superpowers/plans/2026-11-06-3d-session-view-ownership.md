# Three-dimensional task view ownership

**Goal:** Keep the active document's viewport and selection-filter menu consistent when an earlier task is cancelled or receives a late event.

- [x] Notify the main window when the viewport selection filter changes, including task entry, task exit and document view restoration.
- [x] Prevent stale or closed part-sketch tasks from changing or intercepting the current session, and make cleanup idempotent.
- [x] Prevent stale datum tasks and their positioning dialogs from changing viewport previews, markers, grids or picking filters; keep same-session cleanup working.
- [x] Make closed datum tasks and positioning dialogs inert and their cleanup idempotent, including in the same session.
- [x] Prevent stale bound-hole and history-repair actions or late completion callbacks from clearing or replacing the current session's preview.
- [x] Ensure closed task dialogs emit their completion result only once and ignore later accepts or cancels.
- [x] Defer obsolete bound-hole and repair preview cleanup until execution notifications finish; do not erase newer candidates or another session's view.
- [x] Finish queued cancellation after unrelated background work, while blocking restarts and preserving in-flight commits.
- [x] Guard history editor handoff and tie candidate cleanup to the exact displayed snapshot, including late and already-completed candidates.
- [x] Exercise filter restoration, old-session input and cleanup, datum source invalidation, real document switching, and normal modeling and positioning paths.
- [x] Record scoped test results and their software-rendering limitations in the U02/U04 evidence files.
