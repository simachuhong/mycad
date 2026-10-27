# P2-27 — Documentation and governance synchronization

Date: 2026-10-24

## Synchronized records

- README now describes Phase 2 as active work, identifies optional desktop installation, and separates T1, T2 headless/desktop, and T3 no-go statements.
- AGENTS.md now shows `uv sync --extra desktop` for development/UI checks and `uv sync --no-dev` for headless runtime.
- ADR-006 records the implemented split and its evidence boundary. ADR-008 freezes the v1 archive and recovery contract. The ADR document contract now includes eight numbered records.
- NOTICE measures the all-extras, all-platform distribution union. The audit verifies default and `desktop` exports separately.
- The E04 baseline table retains the old observation as a historical defect and points to P2-05's current-geometry pick behavior and explicit history-preview mode.
- P2-12 and P2-19 stay marked partial; P2-26 has an explicit partial evidence record. F1–F4 and the full Phase 2 release gate remain open.

## Verification

`tests/test_adr_docs.py`, `tests/test_notice.py`, and the full `tests/test_scope_audit.py` ran as part of the 50-test scoped result in [P2-25 evidence](task-P2-25-phase2-agent-loop.md). This includes the tracked baseline-document hash guard, import/layering checks, dependency exports, and documentation structure. `git diff --check` passed. The full test suite and the Phase 2 release gate were not run or claimed.
