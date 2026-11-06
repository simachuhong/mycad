# Saved Drawing Arrays Implementation Plan

**Goal:** Let the existing numeric linear and circular array controls create draft copies from saved and mixed selections.

**Architecture:** Use the current workplane projection and existing array geometry functions, preserving source objects and placing only generated copies into draft history. Reuse selection, layer, identity and failure guards from numeric offset. Count includes each original; this does not add associative arrays or reserve 3D command IDs.

- [x] Add failing UI tests for both array types, mixed sources, draft undo and saved reopen.
- [x] Reuse copy-generation and selection validation for arrays; preserve selection and geometry on invalid input.
- [x] Verify restricted layers, ambiguous identities and relevant regressions; update U09 audit to state the supported subset.
