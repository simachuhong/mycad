# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""CommandRegistry tests: conflict policy, version coexistence, category
derivation from the id first segment, and the exact search semantics
(#round9-8: id + all verb aliases + summary_en, case-insensitive substring,
NOT label_zh; sorted by id; [] on no match).
"""

from __future__ import annotations

import pytest

from mycad.commands.registry import CommandRegistry
from mycad.commands.spec import CliSyntax, CommandSpec
from mycad.core.exceptions import CommandConflictError, UnknownCommandError
from tests.commands._fixtures import (
    ALL_COMMAND_IDS,
    DEFS,
    cylinder_spec,
    ping_spec,
    synthetic_registry,
)


def _bare_spec(command_id: str, verb: str = "x") -> CommandSpec:
    return CommandSpec(
        id=command_id,
        version=1,
        summary_en=f"summary of {command_id}",
        label_zh="标签",
        params_schema={"type": "object", "properties": {}, "additionalProperties": False},
        cli=CliSyntax(verb_aliases=(verb,)),
    )


# ---------------------------------------------------------------------------
# register / get / conflicts / versions
# ---------------------------------------------------------------------------


def test_register_and_get_roundtrip() -> None:
    registry = CommandRegistry(schema_defs=DEFS)
    spec = cylinder_spec()
    registry.register(spec)
    assert registry.get("feature.cylinder") is spec


def test_get_unknown_id_raises_unknown_command() -> None:
    registry = CommandRegistry()
    with pytest.raises(UnknownCommandError) as exc_info:
        registry.get("feature.nope")
    assert exc_info.value.identifier == "feature.nope"


def test_duplicate_same_id_same_version_conflicts() -> None:
    registry = CommandRegistry()
    registry.register(cylinder_spec())
    with pytest.raises(CommandConflictError, match="feature.cylinder"):
        registry.register(cylinder_spec())


def test_different_versions_coexist_latest_is_default() -> None:
    registry = CommandRegistry()
    v1 = cylinder_spec()
    v2 = CommandSpec(
        id="feature.cylinder",
        version=2,
        summary_en="Create a cylinder (v2)",
        label_zh="圆柱体",
        params_schema=dict(v1.params_schema),
        cli=CliSyntax(verb_aliases=("cylinder",)),
    )
    registry.register(v1)
    registry.register(v2)
    assert registry.get("feature.cylinder") is v2
    assert registry.get("feature.cylinder", version=1) is v1
    assert registry.get("feature.cylinder", version=2) is v2


def test_get_missing_version_raises() -> None:
    registry = CommandRegistry()
    registry.register(cylinder_spec())
    with pytest.raises(UnknownCommandError):
        registry.get("feature.cylinder", version=7)


def test_schema_defs_is_the_single_injection_point() -> None:
    injected = CommandRegistry(schema_defs=DEFS)
    assert injected.schema_defs == DEFS
    empty = CommandRegistry()
    assert empty.schema_defs == {}


def test_no_module_level_global_state_instances_isolated() -> None:
    left = CommandRegistry()
    right = CommandRegistry()
    left.register(cylinder_spec())
    with pytest.raises(UnknownCommandError):
        right.get("feature.cylinder")
    assert right.list_by_category() == {}


# ---------------------------------------------------------------------------
# verb resolution
# ---------------------------------------------------------------------------


def test_resolve_verb_via_alias() -> None:
    registry = synthetic_registry()
    spec = registry.resolve_verb("cylinder")
    assert spec is not None and spec.id == "feature.cylinder"
    cut_spec = registry.resolve_verb("cut")
    assert cut_spec is not None and cut_spec.id == "modify.boolean_cut"
    assert registry.resolve_verb("nope") is None


def test_resolve_verb_conflict_between_commands() -> None:
    registry = CommandRegistry()
    registry.register(_bare_spec("feature.a", verb="shared"))
    registry.register(_bare_spec("modify.b", verb="shared"))
    with pytest.raises(CommandConflictError, match="shared"):
        registry.resolve_verb("shared")


# ---------------------------------------------------------------------------
# category derivation + list_by_category
# ---------------------------------------------------------------------------


def test_category_derived_from_id_first_segment() -> None:
    registry = synthetic_registry()
    grouped = registry.list_by_category()
    assert set(grouped) == {"feature", "modify", "demo"}
    assert [spec.id for spec in grouped["feature"]] == [
        "feature.box",
        "feature.cylinder",
        "feature.extrude",
        "feature.hole",
        "feature.hole_pattern",
        "feature.revolve",
    ]
    assert len(grouped["feature"]) == 6
    assert [spec.id for spec in grouped["modify"]] == ["modify.boolean_cut", "modify.fillet"]
    assert len(grouped["modify"]) == 2
    assert [spec.id for spec in grouped["demo"]] == ["demo.ping"]


def test_list_by_category_ids_and_categories_sorted() -> None:
    registry = CommandRegistry()
    registry.register(ping_spec())
    registry.register(cylinder_spec())
    grouped = registry.list_by_category()
    assert list(grouped) == ["demo", "feature"]
    assert [spec.id for spec in grouped["demo"]] == ["demo.ping"]


def test_registry_holds_exactly_the_appendix_a_ids() -> None:
    registry = synthetic_registry()
    for command_id in ALL_COMMAND_IDS:
        assert registry.get(command_id).id == command_id


# ---------------------------------------------------------------------------
# search semantics
# ---------------------------------------------------------------------------


def test_search_by_id_substring() -> None:
    registry = synthetic_registry()
    hits = registry.search("cyl")
    assert [spec.id for spec in hits] == ["feature.cylinder"]


def test_search_by_verb_alias() -> None:
    registry = synthetic_registry()
    hits = registry.search("cylinder")
    assert "feature.cylinder" in [spec.id for spec in hits]


def test_search_by_summary_en() -> None:
    registry = synthetic_registry()
    hits = registry.search("Create")
    assert [spec.id for spec in hits] == ["feature.box", "feature.cylinder"]


def test_search_is_case_insensitive() -> None:
    registry = synthetic_registry()
    assert [spec.id for spec in registry.search("CYLINDER")] == ["feature.cylinder"]


def test_search_does_not_search_label_zh() -> None:
    registry = synthetic_registry()
    assert registry.search("圆柱") == []
    assert registry.search("差集") == []


def test_search_no_match_returns_empty_list() -> None:
    registry = synthetic_registry()
    result = registry.search("bogus")
    assert result == []
    assert result is not None


def test_search_results_sorted_by_id() -> None:
    registry = synthetic_registry()
    hits = registry.search("hole")
    assert [spec.id for spec in hits] == ["feature.hole", "feature.hole_pattern"]


def test_search_matches_multiple_fields_deduplicated() -> None:
    # "cylinder" hits feature.cylinder via id AND alias AND summary but the
    # spec must appear exactly once
    registry = synthetic_registry()
    hits = registry.search("cylinder")
    assert len(hits) == 1
