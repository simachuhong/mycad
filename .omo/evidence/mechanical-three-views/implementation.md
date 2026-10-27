# Engineering drawing implementation evidence

Baseline checkpoint: `77ca873`; T0: `6956492`; T1: `fdf2d0e`; T2: `1c52760`.

## T2 — completed

184 scoped regression tests passed (`t2-final.log`), including command catalogs, model provenance, persistence, atomic candidate loading, Bus rollback, drawing coordinates and layering. New commands use archive v3 and retain existing audit records. Annotation cascade delete/undo and unknown-version rejection preserve the current document. CLI view groups round-trip through the actual grammar; explicitly confirmed agent plans use the same handlers.

One `drawing.view.create/update` with a `views` array is one history entry. `execute_batch` supplies rollback but is not advertised as a one-undo group.

## T3 — completed adapter and process boundary

Production adapter preserves exact line/circle/ellipse/rational B-spline curves. Neutral BREP snapshots cross into a persistent spawned process; the live kernel is never shared with that process. Parent UI must still reject stale generations/session/source fingerprints (T5).

Performance debugging, 900-edge fixture, three views:
- Initial complete DTO/provenance pipeline: 19.378 s, failed 3 s target.
- Replace repeated source face scans with an explicit-history hash lookup (still validated with IsSame), and eliminate repeated arc-length integration during geometric matching: 3.942 s.
- Stop extracting face associations after every curve has a source: 2.883 s in an isolated run, but 3.539 s during scoped regression. This is not yet a stable pass.
- Exact spline identity test exposed a correctness hazard in sampled deduplication: two degree-5 splines can coincide at all five sample parameters while differing elsewhere. Full spline data is now used for equality; the adversarial test demonstrably failed before the fix.
- OCCT represents some edge-on conics as collinear splines. Only when their positive-weight poles lie on the endpoint segment can the adapter canonicalize their geometric image to an exact line. Curved splines retain full poles, knots, multiplicities and rational weights.

Canonicalization and adversarial spline checks passed: 10 tests, full 900-edge DTO pipeline 2.983 s (`t3-canonical.log`). A further 22 T0/GUI-heartbeat/layering regressions passed (`t3-regressions.log`). Scoped lint, format and strict typing passed. Performance margin on this machine remains small and will be checked at integration. Worker/session publishing logic remains T5; no final user workflow/export/release claim is made here.
