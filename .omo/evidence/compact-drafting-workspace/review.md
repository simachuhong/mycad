# Fresh task-scoped review

Reviewer: compact_workspace_review (fresh context, read-only).

One Important finding: opening a floating console during inline dimension editing steals focus; Esc then fails to cancel the candidate. Reproduced by reviewer and test_console_open_keeps_inline_dimension_escape (RED timeout on focus return). Fix: defer restoring the active dimension input/canvas focus until the console tab/menu event completes. Covers docked/floating console and CLI/AI/information/plan menu entries. Verified RED → GREEN, all 5 console tests passed; final regression 133/133 passed.

No other concrete findings. No deferred minors. Limitations: Qt offscreen verification, native window-manager interaction not exercised; AI backend intentionally unavailable, explicitly labelled offline.
