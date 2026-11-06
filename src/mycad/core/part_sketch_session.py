# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Independent local draft state for a part sketch."""

from dataclasses import replace

from mycad.core.sketch import Sketch, SketchEntity
from mycad.core.sketch_constraints import SketchConstraint


class PartSketchEditSession:
    """Mutable draft session containing immutable sketch snapshots."""

    def __init__(self, sketch: Sketch) -> None:
        self._sketch = sketch
        self._undo: list[Sketch] = []
        self._redo: list[Sketch] = []
        self._generation = 0
        self._validate_references(sketch)

    @staticmethod
    def _validate_references(sketch: Sketch) -> None:
        identities = {entity.entity_id for entity in sketch.entities}
        if any(
            reference.entity_id not in identities
            for constraint in sketch.constraints
            for reference in constraint.references
        ):
            raise ValueError("constraint references missing sketch geometry")

    @property
    def sketch(self) -> Sketch:
        """Return the current immutable draft."""
        return self._sketch

    @property
    def generation(self) -> int:
        """Identify the current revision of this draft session."""
        return self._generation

    @property
    def states(self) -> tuple[Sketch, ...]:
        """Return the active, undo-aware sequence of accepted draft states."""
        return (*self._undo, self._sketch)

    def replace_sketch(self, sketch: Sketch) -> None:
        """Accept one validated draft edit without altering the support frame."""
        if (
            sketch.sketch_id != self._sketch.sketch_id
            or sketch.frame != self._sketch.frame
            or sketch.support_face != self._sketch.support_face
        ):
            raise ValueError("draft sketch identity, frame and support must remain locked")
        self._validate_references(sketch)
        if sketch == self._sketch:
            return
        self._undo.append(self._sketch)
        self._sketch = sketch
        self._redo.clear()
        self._generation += 1

    def add_entity(self, entity: SketchEntity) -> None:
        """Append one geometry entity as a local undoable edit."""
        self.replace_sketch(replace(self._sketch, entities=(*self._sketch.entities, entity)))

    def delete_entities(self, identities: tuple[str, ...]) -> tuple[SketchConstraint, ...]:
        """Remove selected entities and their relations in a single edit."""
        selected = set(identities)
        if not selected:
            return ()
        if not selected <= {entity.entity_id for entity in self._sketch.entities}:
            raise ValueError("cannot delete missing sketch geometry")
        removed = tuple(
            constraint
            for constraint in self._sketch.constraints
            if any(reference.entity_id in selected for reference in constraint.references)
        )
        self.replace_sketch(
            replace(
                self._sketch,
                entities=tuple(
                    entity for entity in self._sketch.entities if entity.entity_id not in selected
                ),
                constraints=tuple(
                    constraint
                    for constraint in self._sketch.constraints
                    if constraint not in removed
                ),
            )
        )
        return removed

    def undo(self) -> bool:
        """Restore the last draft state without touching document history."""
        if not self._undo:
            return False
        self._redo.append(self._sketch)
        self._sketch = self._undo.pop()
        self._generation += 1
        return True

    def redo(self) -> bool:
        """Reapply the next local draft edit."""
        if not self._redo:
            return False
        self._undo.append(self._sketch)
        self._sketch = self._redo.pop()
        self._generation += 1
        return True
