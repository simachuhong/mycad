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


## T4 — permanent workspaces and placement

`平面草图 | 工程图 | 3D图` are permanent containers. Every previous MainWindow central-widget identity condition now routes via active_workspace. Sketch draft entities, selection, zoom, floating dock state and 3D camera persist; document undo from the engineering page leaves a hidden sketch draft intact. drawing2d retains its spatial preview tab per the approved spec, with engineering generation disabled.

Base/projected views are placed directly on the paper canvas. Enter submits one view-group command; Esc discards the transient group. Model changes pause pending placement pending explicit preview refresh. Uncommitted groups block save/document replacement with an in-canvas completion instruction. A new document clears the old paper scene. Existing sheets fit on first activation; later tab switches preserve the zoom.

Evidence: 96 GUI regressions (`t4-regressions.log`), 27 scoped command/archive/GUI/layering tests (execution ledger), 5 first-activation/camera/capture regressions (`t4-fit-green.log`). Real X11 desktop projection/placement passed (`t4-desktop.log`); normal, 960×600 and floating screenshots are saved alongside this report. Narrow windows preserve the current zoom and offer scrollbars; Fit remains available. Hints are centralized in the shared Info/CLI/offline-AI/Plans console.

Integration corrected a command-schema mismatch: the fixed validator supports const:null, not type:null. Optional absent parent/owner fields are omitted by the DTO serializer, with a full DTO CLI roundtrip regression. Periodic OCCT source splines are normalized by the adapter; the renderer explicitly rejects unnormalized periodic input rather than displaying a false control polygon.

Remaining stages: T5 robust async states and grips, T6 associated dimensions, T7 output, T8 complete workflow/release verification. These screenshots are not evidence of those later features.

## T5 — view handles and asynchronous updates

Paper move/scale/alignment gestures preview without history writes, then submit one command on release. Escape/tab changes cancel capture and preview. Parent motion carries aligned children; child direction constrains motion; scale/display overrides restore inheritance explicitly. Parent deletion previews the subtree and annotation count, requires inline confirmation, and undoes together.

ProjectionUpdates validates session, model fingerprint, view UUID and request generation. New model requests coalesce; cancellation includes queued captures; failed/diagnostic results retain old geometry with stale/failed styling. Worker death restarts the pool for explicit retry. Layout-only edits do not submit projection work. 29 scoped tests pass; strict typing/lint/format pass. Isolated 300/900-edge process heartbeat gates pass, 900-edge maximum UI gap 0.102s. A concurrent-load 3.585s timing failure is retained in t5-heartbeat.log; isolated t5-heartbeat-isolated.log passes without relaxing the 3s threshold.

## T6 — associated measurements

Added bounded semantic resolution with pre-deduplication source counts. Cylinder axis predicates survive radius edits; edge-on planar predicates support simple side-length edits. Multiple source faces or projected candidates are ambiguous; missing sources are orphaned, preserving text position and blocking output. No nearest-edge or topology-index rebinding. These are bounded predicates, not unrestricted persistent topology naming; coaxial or otherwise indistinguishable features may need a different uniquely identifiable reference.

Horizontal/vertical/aligned lengths, radius/diameter, angle, center marks/lines now produce shared frozen annotation geometry. Values use unscaled projected millimetres. Ellipses reject circular dimensions; angle sectors follow text placement; trimmed-arc leaders hit the actual arc. Canvas clicks place dimensions, text drags submit once, double-click opens the floating format tab, and reattachment preserves annotation identity/expression. Source changes prevent committing stale drafts. Actual X11 test and t6-annotation-desktop.png inspected. 60 broader regressions and final 44 scoped tests passed, with lint/format/type clean. Full 900-edge DTO timing regressed to 3.529s, then passed at 2.835s after lazy shared provenance caching; both logs retained.
