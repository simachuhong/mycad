# Phase-2 representative-part scenarios

`examples/representative_parts.json` defines 30 stable cases across flange, shaft/sleeve, mounting plate, cover, and boundary categories. It distinguishes the initial 18 command-expression candidates, six explicit rejections, and six extension candidates. The supported label records that the listed command chain is expressible; it does not claim the later end-to-end gate is complete.

`examples/parameter_perturbations.json` contains 108 explicit perturbation/restore records linked from the catalog. Thirty primitive-only scenarios execute now through `CommandBus.edit_and_replay`, compare analytic volume and BREP bounds, then restore the baseline. Seventy-eight full-chain scenarios remain marked `gated` by P2-32–37; their expected geometry, measurement, reference, and restore outcomes are recorded rather than represented as passing tests.

The executable regression also creates and measures a flange, edits an upstream radius, exercises undo/redo, saves and reopens `.mc.json`, and checks a STEP round trip with volume tolerance. Full P2-19 acceptance remains partial until the gated profile/sketch/feature workflows are implemented.
