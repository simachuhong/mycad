# P2-20 — Plan content and execution authorization

Date: 2026-10-24

## Result

E05 is blocked. A confirmed plan can execute only with a Bus-issued grant bound to its `plan_id`, actor, GUI/CLI scope, normalized command content digest, in-memory document identity, and monotonic document revision. The content digest is a binding field; a separate random nonce and HMAC signature form the capability. The Bus consumes each nonce once, before entering the batch state machine.

`Document.document_id` is generated for each in-memory document instance and is not persisted. `Document.revision` advances on committed Bus history operations (execute, batch, undo, redo, edit/replay), direct annotation mutations (metadata and named groups), and the public direct history-amendment entry point. Undo and redo advance it even if the resulting history length returns to an earlier value. Bus edit/replay defers its revision increment until replay commits. A failed batch with no annotation mutation leaves the revision unchanged; rollback never decrements revisions already issued by nested annotation mutations.

The plan editor rejects edits outside `draft`. The Bus also recomputes normalized content before execution, so direct post-confirmation tampering cancels the stale plan. Switching documents, changing the document revision, invalid parameters, invalid signatures, copied/replayed grants, and actor/plan mismatches are rejected before command execution. A geometry failure rolls back atomically and leaves the plan `failed`; the user starts a replacement draft and confirms it again. GUI confirmation uses scope `gui`; an explicitly invoked CLI plan/batch uses `cli`. The requested execution scope is checked against the signed grant before the nonce is consumed, so a wrong-scope attempt cannot use a grant through the other product path. No Agent scope or Agent execution path was added.

The `.mc.json` v1 schema and the existing six command audit fields are unchanged. Identity, revision, digest, nonce, and signature remain runtime-only. No exception type, dependency, LLM, MCP, remote token service, or enterprise authorization backend was added.

## Verification

- RED/GREEN: the new non-JSON content tampering test first failed because `NaN` raised `ValueError` during digest serialization; the Bus now invalidates the stale plan and the focused test passes.
- `uv run pytest tests/core/test_document.py tests/core/test_plan_state_machine.py tests/core/test_bus.py tests/core/test_core_integration.py tests/ui/test_plan_confirm.py tests/cli/test_run_json.py tests/cli/test_batch.py tests/cli/test_repl.py tests/test_acceptance_flange.py tests/test_layering.py tests/test_exceptions.py -q` — 183 passed.
- Scoped `ruff check` — passed.
- Scoped `ruff format --check` — 14 files already formatted.
- Scoped `basedpyright` — 0 errors, 0 warnings, 0 notes.
- `git diff --check` — passed.

Independent review found and reproduced a gap where public `Document.replace_command_params()` changed history without advancing the revision. A regression test failed at the unchanged revision before the fix; the public method now advances revision, while Bus replay uses a private deferred helper and advances once after successful replay. A separate scope-mismatch regression test confirms that a GUI grant is rejected on CLI execution and remains usable only through the GUI path. Independent follow-up review reported no remaining actionable issues.

Invalid CLI batch parameters are rejected during explicit plan confirmation before any geometry mutation. The CLI tests now assert this pre-execution rejection; geometry-level batch failures continue to verify rollback and the failed-plan state.
