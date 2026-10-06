# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Document aggregate tests (T6b): metadata, dirty flag, groups, amendments."""

from __future__ import annotations

from typing import cast

import pytest

from mycad.commands.demo import demo_registry
from mycad.core.document import Document, ExecutedCommand
from mycad.core.exceptions import InvalidHistoryError, ValidationError
from mycad.core.groups import NamedGroup

# ---------------------------------------------------------------- metadata --


def test_new_document_metadata_defaults() -> None:
    doc = Document(demo_registry())
    assert doc.metadata == {"part_no": "", "revision": "", "material": "", "source": "local"}


@pytest.mark.parametrize(
    "key",
    ["part_no", "revision", "material", "source", "part_name", "notes"],
)
def test_set_metadata_whitelist_roundtrip(key: str) -> None:
    doc = Document(demo_registry())
    doc.set_metadata(key, "value-1")
    assert doc.metadata[key] == "value-1"


def test_set_metadata_unknown_key_rejected() -> None:
    doc = Document(demo_registry())
    with pytest.raises(ValidationError):
        doc.set_metadata("plm_custom_attr", "x")


def test_set_metadata_non_string_value_rejected() -> None:
    doc = Document(demo_registry())
    with pytest.raises(ValidationError):
        doc.set_metadata("part_no", cast("str", 123))


def test_set_metadata_emits_exactly_one_signal_per_call() -> None:
    doc = Document(demo_registry())
    seen: list[object] = []
    doc.events.subscribe("metadata_changed", seen.append)
    doc.set_metadata("part_no", "A-1")
    assert seen == [{"key": "part_no", "value": "A-1"}]


def test_dirty_flag_set_and_mark_clean() -> None:
    doc = Document(demo_registry())
    assert doc.is_dirty is False
    doc.set_metadata("part_no", "A-1")
    assert doc.is_dirty is True
    doc.mark_clean()
    assert doc.is_dirty is False


def test_constructor_unknown_metadata_key_rejected() -> None:
    with pytest.raises(ValidationError):
        Document(demo_registry(), metadata={"bogus": "x"})


# ------------------------------------------------------------------ groups --


def test_add_named_group_emits_once_and_stores() -> None:
    doc = Document(demo_registry())
    seen: list[object] = []
    doc.events.subscribe("named_group_added", seen.append)
    group = NamedGroup(name="top-faces")
    doc.add_named_group(group)
    assert seen == [{"name": "top-faces"}]
    assert doc.named_groups == {"top-faces": group}


def test_add_named_group_duplicate_name_rejected() -> None:
    doc = Document(demo_registry())
    doc.add_named_group(NamedGroup(name="g"))
    with pytest.raises(ValidationError):
        doc.add_named_group(NamedGroup(name="g"))
    assert len(doc.named_groups) == 1


def test_add_named_group_empty_name_rejected() -> None:
    doc = Document(demo_registry())
    with pytest.raises(ValidationError):
        doc.add_named_group(NamedGroup(name=""))


def test_add_named_group_non_string_name_rejected() -> None:
    doc = Document(demo_registry())
    with pytest.raises(ValidationError):
        doc.add_named_group(NamedGroup(name=cast("str", 123)))


def test_remove_named_group_emits_once_and_updates_view() -> None:
    doc = Document(demo_registry())
    doc.add_named_group(NamedGroup(name="g"))
    seen: list[object] = []
    doc.events.subscribe("named_group_removed", seen.append)
    doc.remove_named_group("g")
    assert seen == [{"name": "g"}]
    assert doc.named_groups == {}


def test_remove_missing_named_group_raises_keyerror() -> None:
    doc = Document(demo_registry())
    with pytest.raises(KeyError):
        doc.remove_named_group("nope")


def test_named_groups_property_is_a_copy() -> None:
    doc = Document(demo_registry())
    doc.add_named_group(NamedGroup(name="g"))
    snapshot = doc.named_groups
    doc.remove_named_group("g")
    assert snapshot == {"g": NamedGroup(name="g")}
    assert doc.named_groups == {}


# ------------------------------------------------------ command amendments --


def _document_with_cylinder() -> Document:
    command = ExecutedCommand(
        id="feature.cylinder",
        version=1,
        params={"radius": 1.0, "height": 2.0},
        ordinal=0,
        timestamp_utc="2026-01-01T00:00:00+00:00",
        confirmed_by=None,
    )
    return Document(demo_registry(), commands=[command])


def test_replace_command_params_legal_amendment() -> None:
    doc = _document_with_cylinder()
    amended: list[object] = []
    doc.events.subscribe("command_amended", amended.append)
    revised = doc.replace_command_params(
        0, {"radius": 3.0, "height": 2.0}, actor="alice", reason="wider"
    )
    assert amended == [{"ordinal": 0, "command_id": "feature.cylinder"}]
    assert len(revised.amendments) == 1
    entry = revised.amendments[0]
    assert entry.from_params == {"radius": 1.0, "height": 2.0}
    assert entry.actor == "alice"
    assert entry.reason == "wider"
    assert revised.id == "feature.cylinder"
    assert revised.version == 1
    assert revised.ordinal == 0
    assert revised.timestamp_utc == "2026-01-01T00:00:00+00:00"
    assert revised.confirmed_by is None
    assert revised.params == {"radius": 3.0, "height": 2.0}
    assert doc.commands == (revised,)
    assert doc.is_dirty is True


def test_replace_command_params_invalid_leaves_document_untouched() -> None:
    doc = _document_with_cylinder()
    amended: list[object] = []
    doc.events.subscribe("command_amended", amended.append)
    with pytest.raises(ValidationError):
        doc.replace_command_params(0, {"radius": -1.0, "height": 2.0}, actor="bob", reason="bad")
    assert len(doc.commands) == 1
    assert doc.commands[0].amendments == ()
    assert doc.commands[0].params == {"radius": 1.0, "height": 2.0}
    assert amended == []
    assert doc.is_dirty is False


def test_replace_command_params_ordinal_out_of_range() -> None:
    doc = _document_with_cylinder()
    with pytest.raises(InvalidHistoryError):
        doc.replace_command_params(5, {"radius": 3.0, "height": 2.0}, actor="a", reason="r")
