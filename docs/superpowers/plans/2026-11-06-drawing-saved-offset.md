# Saved Drawing Offset Implementation Plan

**Goal:** Allow the existing signed-distance offset control to copy selected saved and draft 2D entities into the draft without modifying source geometry.

**Architecture:** Feed the existing geometric offset function the current workplane's projected saved entities and draft entities together. Retain only generated copies in the draft, preserve the source IDs and history, and use existing draft undo/save. Validate selection uniqueness and locked/hidden layers before changing anything; unsupported geometry and invalid distance leave all geometry unchanged.

**Tech Stack:** Python, PySide6, pytest-qt.

- [x] Write and run failing real-window tests for saved/draft mixed selection, coordinates and identity, undo, save/reopen and failure preservation.
- [x] Implement numeric offset for saved selection using the existing geometric operation and selection validation.
- [x] Run focused tests, UI regressions and path-level lint, formatting and type checks; update the U09 audit with the remaining interactive OFFSET gaps.
