# SDD ledger — plan: docs/superpowers/plans/2026-10-28-drawing-annotation-entry.md
Baseline: 89fabe2. Pre-flight Task1 DrawingNote/scene/PaperText -> Task2 canvas/tools/Bus; aligned.
Ruling: Proceed under explicit user correction in current checkout, preserving running GUI and user Logo assets. No approval or merge/push menu; cost: current branch retains accumulated features.
Ruling: Standalone plain paper notes, not geometry annotations; no leaders/rich text/rotation. Cost: those formats need a later extension.
Ruling: Scoped checks per AGENTS.md rather than full-project repeats; cost: untouched subsystems not rechecked.
Task 1: complete (commits 89fabe2..531c1fb, tests: uv run pytest tests/core/test_drawing_notes.py tests/core/test_drawing_model.py tests/core/test_drawing_archive.py tests/formats/test_drawing_export.py -q → 21 passed in 8.03s)
Task 2: complete (commits 531c1fb..16f5c2d, tests: uv run pytest tests/ui/test_drawing_note_tools.py tests/ui/test_drawing_annotations.py tests/ui/test_sketch_paper_view.py tests/ui/test_drawing_pdf.py tests/ui/test_drawing_start.py tests/ui/test_workspace_tabs.py tests/test_layering.py -q → 51 passed in 52.43s)

Final: Accepted Important findings: literal DXF %%/caret escapes and new-sheet/editor lifecycle. Tests reproduced both failures.
Final: Ruling: Prevent new sheet creation until active text is completed/cancelled, preserving the draft instead of silently discarding it on a paper change. Cost: users finish one text edit before creating another sheet.
Final: fixed literal DXF control sequences — test_note_dxf_literal_percent_and_caret_sequences RED→GREEN, final scoped suite261/261.
Final: fixed new-sheet editor lifecycle — test_new_sheet_preserves_active_text_until_completion RED→GREEN, final scoped suite261/261.
Final review: two Important findings fixed in one pass; no Critical/Minor, Declined to judge none, deferred minors none. Lint/format/type gates pass. Keep current local branch for GUI testing; no push/merge or restart of user process.
