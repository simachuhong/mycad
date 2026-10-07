# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""resolve_manifest field-level tests (T9a).

Reason assertions always compare against constants derived from the
contract Literal via get_args; the skip codes never appear in this
file's docstrings.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import get_args

import pytest

from mycad.plugins.manifest import resolve_manifest
from mycad.plugins.types import WARNING_REASON, PluginManifest

#: Contract source-order lock (types.py pins the Literal order; the
#: index-based derivations across this file depend on it).
REASONS: tuple[str, ...] = get_args(WARNING_REASON)


def test_reason_source_order_locked() -> None:
    assert REASONS[0] == "missing-manifest"
    assert REASONS[1] == "manifest-error"
    assert REASONS[2] == "incompatible-api"


def test_dict_form_minimal_builds_manifest_with_defaults() -> None:
    module = SimpleNamespace(
        manifest={"id": "demo.plugin", "version": "1.0.0", "api_version": "1.0"}
    )
    manifest, reason = resolve_manifest(module)
    assert reason is None
    assert manifest == PluginManifest(id="demo.plugin", version="1.0.0", api_version="1.0")


def test_dict_form_normalizes_permissions_and_keeps_homepage() -> None:
    module = SimpleNamespace(
        manifest={
            "id": "demo.plugin",
            "version": "1.0.0",
            "api_version": "1.5",
            "permissions": ["io.read", "io.write"],
            "homepage": "https://example.invalid",
        }
    )
    manifest, reason = resolve_manifest(module)
    assert reason is None
    assert manifest is not None
    assert manifest.permissions == ("io.read", "io.write")
    assert manifest.homepage == "https://example.invalid"
    assert manifest.api_version == "1.5"


def test_callable_form_returning_dict_resolves(plugin_fixture_path: None) -> None:
    module = importlib.import_module("mycad_plugin_manifest_callable")
    before: int = module.CALL_COUNT[0]
    manifest, reason = resolve_manifest(module)
    after: int = module.CALL_COUNT[0]
    assert reason is None
    assert manifest is not None
    assert manifest.id == "manifest-callable"
    assert after - before == 1


def test_callable_form_returning_manifest_instance() -> None:
    built = PluginManifest(id="cb.instance", version="2.0.0", api_version="1.0")
    module = SimpleNamespace(manifest=lambda: built)
    manifest, reason = resolve_manifest(module)
    assert reason is None
    assert manifest is built


def test_callable_form_raising_is_damaged() -> None:
    def boom() -> dict[str, object]:
        raise RuntimeError("no manifest for you")

    manifest, reason = resolve_manifest(SimpleNamespace(manifest=boom))
    assert manifest is None
    assert reason == REASONS[1]


def test_callable_form_returning_junk_is_damaged() -> None:
    manifest, reason = resolve_manifest(SimpleNamespace(manifest=lambda: 42))
    assert manifest is None
    assert reason == REASONS[1]


def test_manifest_instance_attribute_used_directly() -> None:
    built = PluginManifest(id="direct.instance", version="1.0.0", api_version="1.0")
    manifest, reason = resolve_manifest(SimpleNamespace(manifest=built))
    assert reason is None
    assert manifest is built


def test_instance_form_is_gated_on_api_major_too() -> None:
    built = PluginManifest(id="direct.future", version="1.0.0", api_version="2.0")
    manifest, reason = resolve_manifest(SimpleNamespace(manifest=built))
    assert manifest is None
    assert reason == REASONS[2]


def test_missing_attribute_and_explicit_none_both_report_absence() -> None:
    assert resolve_manifest(SimpleNamespace()) == (None, REASONS[0])
    assert resolve_manifest(SimpleNamespace(manifest=None)) == (None, REASONS[0])


@pytest.mark.parametrize("plugin_id", ["a", "0", "a-b_c.d9", "x9_-.z"])
def test_id_pattern_legal_values_pass(plugin_id: str) -> None:
    module = SimpleNamespace(manifest={"id": plugin_id, "version": "1.0.0", "api_version": "1.0"})
    manifest, reason = resolve_manifest(module)
    assert reason is None
    assert manifest is not None
    assert manifest.id == plugin_id


@pytest.mark.parametrize("plugin_id", ["Bad Id", "UPPER", "sp ace", ""])
def test_id_pattern_illegal_values_are_damaged(plugin_id: str) -> None:
    module = SimpleNamespace(manifest={"id": plugin_id, "version": "1.0.0", "api_version": "1.0"})
    manifest, reason = resolve_manifest(module)
    assert manifest is None
    assert reason == REASONS[1]


def test_permissions_wrong_shape_and_homepage_wrong_type_are_damaged() -> None:
    bad_permissions = SimpleNamespace(
        manifest={
            "id": "p.wrong",
            "version": "1.0.0",
            "api_version": "1.0",
            "permissions": "io.read",
        }
    )
    assert resolve_manifest(bad_permissions) == (None, REASONS[1])
    bad_permission_item = SimpleNamespace(
        manifest={
            "id": "p.item",
            "version": "1.0.0",
            "api_version": "1.0",
            "permissions": [1, 2],
        }
    )
    assert resolve_manifest(bad_permission_item) == (None, REASONS[1])
    bad_homepage = SimpleNamespace(
        manifest={
            "id": "p.home",
            "version": "1.0.0",
            "api_version": "1.0",
            "homepage": None,
        }
    )
    assert resolve_manifest(bad_homepage) == (None, REASONS[1])


def test_permissions_tuple_form_stays_tuple() -> None:
    module = SimpleNamespace(
        manifest={
            "id": "p.tuple",
            "version": "1.0.0",
            "api_version": "1.0",
            "permissions": ("io.read",),
        }
    )
    manifest, reason = resolve_manifest(module)
    assert reason is None
    assert manifest is not None
    assert manifest.permissions == ("io.read",)
    assert isinstance(manifest.permissions, tuple)


def test_empty_api_version_is_damaged_not_unparseable() -> None:
    module = SimpleNamespace(manifest={"id": "api.empty", "version": "1.0.0", "api_version": ""})
    assert resolve_manifest(module) == (None, REASONS[1])


def test_api_gate_wins_over_other_field_damage() -> None:
    module = SimpleNamespace(manifest={"id": "Bad Id", "version": 1.0, "api_version": "2.0"})
    assert resolve_manifest(module) == (None, REASONS[2])


@pytest.mark.parametrize(
    ("module_name", "reason_index"),
    [
        ("mycad_plugin_bad.missing_attr", 0),
        ("mycad_plugin_bad.bad_missing", 1),
        ("mycad_plugin_bad.bad_extra", 1),
        ("mycad_plugin_bad.bad_types", 1),
        ("mycad_plugin_bad.bad_id", 1),
    ],
)
def test_bad_fixture_submodules_report_planned_reasons(
    plugin_fixture_path: None, module_name: str, reason_index: int
) -> None:
    module = importlib.import_module(module_name)
    manifest, reason = resolve_manifest(module)
    assert manifest is None
    assert reason == REASONS[reason_index]


@pytest.mark.parametrize(
    ("module_name", "expected_api", "loads"),
    [
        ("mycad_plugin_matrix.api_1_0", "1.0", True),
        ("mycad_plugin_matrix.api_1_5", "1.5", True),
        ("mycad_plugin_matrix.api_2_0", "2.0", False),
        ("mycad_plugin_matrix.api_v1", "v1", False),
        ("mycad_plugin_matrix.api_abc", "abc", False),
    ],
)
def test_matrix_api_gate(
    plugin_fixture_path: None, module_name: str, expected_api: str, loads: bool
) -> None:
    module = importlib.import_module(module_name)
    manifest, reason = resolve_manifest(module)
    if loads:
        assert reason is None
        assert manifest is not None
        assert manifest.api_version == expected_api
    else:
        assert manifest is None
        assert reason == REASONS[2]
