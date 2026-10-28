# SDD ledger — plan: docs/superpowers/plans/2026-10-28-sketch-paper-view.md
Baseline: 3a887cf, prior entry/Delete fixes checkpointed before adding the clarified source type.
Pre-flight: Task1 SourceBinding/codec -> Task2 source references -> Task3 request.source/sketch_id and generation flow -> Task4 shared scene/export; interfaces aligned.
Ruling: Continue current checkout and native execution under the user's explicit correction and prior implementation authorization; no additional design-approval pause. Cost: preserve existing local history and validate all touched interfaces.
Ruling: Source geometry uses local U/V; source driving annotations are not copied, engineering annotations remain independent reference dimensions. Cost: existing sketch dimension formatting must be recreated on the paper if desired.
Task 1: complete (commits 3a887cf..17a8f86, tests: uv run pytest tests/core/test_sketch_paper_archive.py tests/core/test_drawing_archive.py tests/core/test_drawing_model.py -q → 17 passed in 7.75s)

Task 2: Ruling: Plan names nonexistent tests/core/test_drawing_annotations.py; use existing tests/ui/test_drawing_annotations.py instead, exercising the same annotation path with Qt offscreen. No product scope change.
Task 2: complete (commits 17a8f86..dc7031d, tests: uv run pytest tests/core/test_drawing_sketch.py tests/ui/test_drawing_annotations.py -q → 22 passed in 9.89s)
Task 3: complete (commits dc7031d..b31a375, tests: uv run pytest tests/ui/test_sketch_paper_view.py tests/ui/test_drawing_start.py tests/ui/test_drawing_views.py tests/ui/test_drawing_updates.py tests/ui/test_workspace_tabs.py -q → 30 passed in 36.92s)

Task 4: Ruling: Pure 2D update can complete in the Bus event callback; integration checks either blocked output or the new 60 mm value, never an artificial asynchronous delay. Cost: tests depend on result freshness, not worker timing.
Task 4: Ruling: A deliberately hidden/frozen flat view is a clean empty result; allow output if another view still has geometry. Keep blocking wholly empty sheets and unresolved annotations. Existing gate rejected any empty view and failed the mixed-source test. Cost: clean empty individual views no longer block a populated sheet.

Final workflow Ruling: Keep the current feature branch for local testing; no merge/push menu or new checkout is needed under the existing user scope. Use path-scoped checks per AGENTS.md rather than repeating the prior full-project suite. Cost: untouched subsystems are not revalidated this turn.
Task 4: complete (commits b31a375..cc62926, tests: uv run pytest tests/ui/test_sketch_paper_view.py tests/ui/test_drawing_pdf.py tests/formats/test_drawing_export.py tests/test_layering.py -q → 24 passed in 23.23s)

Final review: fresh gpt-6-astra review of 3a887cf..cc62926. No Critical/Important/Minor findings; Declined to judge: none. Independent targeted tests 10 passed in 12.82s. Deferred minors: none.
