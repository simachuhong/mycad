# P2-37: Inline-tool Boolean intersection

## Status

Bounded implementation slice; P2-37 and P2 G remain partial.

## User workflow

Select **Intersection**, place a box or cylinder tool on the XY workplane, inspect the candidate preview, and explicitly confirm. The command intersects the current model with the placed tool and keeps only the common volume. The inline tool is consumed by the operation.

## Contract

- Release `modify.boolean_intersect@1` with one required `tool` parameter using the existing box/cylinder inline-tool schema.
- Tool placement, parameter serialization, CLI, plan validation, preview, confirmation, Bus history, undo/redo, and archive reopen all use the same normalized command parameters.
- Execute `existing & tool`. The current model must exist and the result must contain a valid nonempty solid. Invalid, disjoint, or empty results fail before history mutation.
- The command is deterministic and replayable. It stores no runtime body IDs, selectors, or inferred geometry fingerprints.
- Use one distinct affected-object value, `intersection_tool_body`, so planned-command auditing remains unambiguous.

## Deliberate limits

- The selected input is the current aggregate model plus one inline box/cylinder; this is not arbitrary body-to-body selection.
- The tool body is consumed. Retaining the tool and choosing targets/results are not supported.
- No face/sheet intersections, multi-tool sets, split results, or keep-both mode.
- Persistent BodyId, feature lineage, and topology references are not introduced. Those require a separate persistence/recovery decision under ADR-008.
- This slice does not close P2-37, P2-36, P2-34, P2-35, P2-19, or P2-44 and has no Solid Edge desktop acceptance claim.

## Solid Edge comparison

Siemens' BooleanFeatures API lists intersect, unite, and subtract as distinct Boolean operations, and specifies solid-body tools for intersection. The MyCAD slice follows the operation and preview/confirm intent while restricting the tool to an explicit primitive because durable model-to-model references are not yet specified.

Reference: [Solid Edge BooleanFeatures.Add API](https://support.industrysoftware.automation.siemens.com/trainings/se/106/api/SolidEdgePart~BooleanFeatures~Add.html).
