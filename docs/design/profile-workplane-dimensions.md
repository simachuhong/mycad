# Profile, Work Plane, and Dimension Prototype

Status: phase-2 design decision and value-only prototype. This record does not add a command, solver, GUI sketch editor, or `.mc.json` v1 field.

## Coordinate frame

Each profile sketch owns a right-handed local frame expressed in millimetres. `origin_mm` is a point in model coordinates; `u_axis` and `v_axis` are unit directions; `normal = u_axis × v_axis`. The axes must be finite, orthonormal, and right-handed. Local 2D profile coordinates remain separate from model-space coordinates until an explicit geometry command maps them through the frame.

The current prototype accepts arbitrary oblique frames. Existing `CircleProfile` and `RectProfile` remain XY-at-z=0 inputs, preserving their current command representation and behavior.

## Contours and construction geometry

`WireContour` stores a closed polygonal loop as local `(u, v)` millimetre values. The closing segment is implicit; the first vertex is not repeated. Outer loops use counterclockwise winding and holes use clockwise winding. Loops require at least three finite vertices and nonzero area. A hole must be inside an outer loop. This prototype does not infer tangency, solve constraints, heal self-intersections, or turn invalid wires into valid ones.

`ConstructionSegment2D` is a separate open guide entity. It is excluded from contour area and from model solids. Later curve types can extend the sketch entity model without treating a construction segment as a boundary edge.

## Dimensions and entity boundary

`DimensionLabel` stores a finite value, explicit `mm` or `deg` unit, and a `driving` or `reference` kind. Driving means a future solver input; reference means a measured/display-only label. This prototype records that distinction but has no solver behavior and does not derive dimensions from geometry.

Profile entities are 2D sketch values. They are not `FeatureId`, `BodyId`, `TopologyId`, `Face`, or `Edge` model entities. A future command will consume a validated sketch/profile and create 3D model history through CommandBus; it must not write sketch state directly into the BREP kernel.

## Reference lifecycle and persistence questions

External model-edge projection into a sketch remains an unresolved reference, not a copied construction line with implied permanence. Before implementation, P2-24 must decide how references name source history, how edits/deletions invalidate projected geometry, how undo/redo restores it, and how ambiguity is reported without rank fallback.

P2-24 must also decide whether sketches are ordinary replayable history commands or a separately versioned archive section, how dimension identifiers survive edits, and whether construction geometry and reference dimensions are persisted. Until that decision, `ProfileSketch.to_mapping()` is a JSON-compatible test/prototype representation only; it is not accepted by archive v1 and must not be saved into `.mc.json`.

## Prototype boundary

The neutral immutable classes live beside the existing XY profile values in `mycad.geom.profiles`, use only standard-library types, and round-trip through explicit mapping methods. They introduce no CAD backend dependency into `mycad.core`, no solver, no new command IDs, and no archive migration.
