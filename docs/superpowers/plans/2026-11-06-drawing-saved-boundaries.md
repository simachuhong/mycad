# Saved Drawing Trim and Extend Boundaries Implementation Plan

**Goal:** Let visible saved 2D geometry act as a read-only boundary when trimming, extending or splitting draft geometry.

**Architecture:** Keep picking and mutation restricted to draft targets. Feed draft geometry plus visible projected saved curves to existing edit operations and retain only draft results. Use the same boundary set for hover preview, clicks and drag trim. Reject ambiguous identities instead of guessing; hidden/frozen boundaries do not participate, and locked boundaries may be used without modifying them.

- [x] Add failing real-window tests for trim, extend and split against saved boundaries, including preview, undo and unchanged source history.
- [x] Centralize boundary-aware operations so clicks, previews and drag trimming share results and never append source objects to the draft.
- [x] Test hidden and locked boundary visibility, duplicate identities, preview, drag undo, save/reopen and regression of existing draft edits; run scoped lint, format and types and document the remaining saved-target limitation.
