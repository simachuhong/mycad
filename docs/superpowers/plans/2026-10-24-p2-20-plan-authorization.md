# P2-20 Plan Authorization Implementation Plan

> **For agentic workers:** Implement each item with a failing test first, then make the smallest change that passes it.

**Goal:** Bind each confirmed plan execution to its normalized command content, the exact in-memory document identity and monotonic document revision, and a one-time product-side authorization.

**Architecture:** `CommandBus.confirm_plan()` validates and normalizes plan steps, computes a canonical content digest, and creates an opaque HMAC-backed grant scoped to `gui` or `cli`. `Document` exposes a runtime identity and monotonic revision advanced after committed Bus history changes and direct document mutations; `execute_batch()` checks the grant, including the caller's scope, and all bindings before entering the existing atomic six-state execution flow. GUI draft edits are accepted only while draft; GUI and CLI callers explicitly request a grant at their confirmation points.

**Tech Stack:** Python stdlib `hashlib`, `hmac`, `json`, `secrets`, `uuid`; existing `CommandBus`, `Document`, `Plan`, Qt card UI, and CLI.

**Spec:** `.omo/plans/phase2-agent-loop.md` P2-20 and `.omo/evidence/task-P2-00-phase2-agent-loop.md` E05.

## Tasks

- [x] Add failing core tests for document identity/revision, confirmation binding, normalized digest, mutation/undo/redo invalidation, consumed/forged grants, and rollback/reconfirmation.
- [x] Add failing UI/CLI tests showing post-confirm draft edits are blocked and the explicit GUI/CLI confirmation paths authorize exactly one execution.
- [x] Implement document identity/revision. Successful Bus history operations advance after commit; direct annotation and public history edits advance on mutation. Bus replay defers revision until commit; rollback never decrements revisions already issued by nested document mutations.
- [x] Implement `CommandBus.confirm_plan()` and one-time scoped authorization verification before `execute_batch()` mutates state; keep `Plan.confirm()` as the six-state transition primitive.
- [x] Route plan-card execution and CLI plan execution through the bus confirmation API; freeze controller edits after confirmation and report stale confirmation clearly.
- [x] Run scoped tests and the project’s incremental static gates for touched paths; record evidence and update P2-20 status only if every listed criterion is met.

## Constraints

- Preserve the exact fifteen-class exception taxonomy; reuse `InvalidPlanTransition` for rejected authorization.
- Preserve the `.mc.json` v1 schema and its six audit fields; document identity/revision and authorization are runtime-only.
- Do not add Agent, LLM, MCP, remote-token service, permissions backend, or new dependencies.
- User-initiated CLI invocation and GUI confirmation each get explicit scopes; neither scope is an Agent capability.
