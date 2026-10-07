# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""In-process tests for the demo plugin module (T9c).

No installation involved: the demo package's ``src`` directory is placed
on ``sys.path`` for the duration of each test and removed afterwards
(same injection discipline as the T9a fixture trees). The module is
imported dynamically — the demo package is a separate distribution and
must stay outside the main import graph.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from dataclasses import fields as dataclass_fields
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest

from mycad.core.handlers import CommandHandler, HandlerContext
from mycad.core.kernel_protocol import Kernel

#: tests/plugins/test_demo_module.py -> parents[2] is the repository root.
DEMO_SRC: Path = (
    Path(__file__).resolve().parents[2] / "plugins_examples" / "mycad_plugin_demo" / "src"
)

#: The eight FormatProvider field names pinned by the T8 contract.
_PROVIDER_FIELDS: frozenset[str] = frozenset(
    {"name", "vendor", "priority", "extensions", "can_read", "can_write", "target", "_writer"}
)


@pytest.fixture
def demo() -> Iterator[ModuleType]:
    """Import the demo package with its src root on sys.path, then un-inject."""

    entry = str(DEMO_SRC)
    if entry not in sys.path:
        sys.path.insert(0, entry)
    try:
        yield importlib.import_module("mycad_plugin_demo")
    finally:
        if entry in sys.path:
            sys.path.remove(entry)


def test_manifest_dict_fields_verbatim(demo: ModuleType) -> None:
    manifest: dict[str, object] = demo.manifest
    assert manifest["id"] == "mycad-plugin-demo"
    assert manifest["version"] == "0.1.0"
    assert manifest["api_version"] == "1.0"
    assert set(manifest) == {"id", "version", "api_version"}


def test_spec_seven_fields_verbatim(demo: ModuleType) -> None:
    spec = demo.DEMO_PING_SPEC
    assert spec.id == "demo.ping"
    assert spec.version == 1
    assert spec.summary_en == "Ping the demo plugin"
    assert spec.label_zh == "演示：心跳"
    assert spec.cli.verb_aliases == ("ping",)
    assert spec.undo_compensation == "history_replay"


def test_spec_params_schema_shape(demo: ModuleType) -> None:
    schema = demo.DEMO_PING_SPEC.params_schema
    assert schema == {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }
    assert schema["additionalProperties"] is False


def test_handler_returns_pong(demo: ModuleType) -> None:
    handler = demo.DemoPingHandler()
    assert handler.command_id == "demo.ping"
    ctx = HandlerContext(cast("Kernel", None), "demo.ping")
    assert handler.handle({}, ctx) == "pong"


def test_handler_satisfies_command_handler_protocol(demo: ModuleType) -> None:
    assert isinstance(demo.DemoPingHandler(), CommandHandler)


def test_commands_factory_single_contribution(demo: ModuleType) -> None:
    contributions = demo.commands()
    assert len(contributions) == 1
    assert contributions[0].spec is demo.DEMO_PING_SPEC
    assert contributions[0].handler_factory is demo.DemoPingHandler


def test_txt_summary_provider_eight_fields_verbatim(demo: ModuleType) -> None:
    provider = demo.TXT_SUMMARY_PROVIDER
    assert provider.name == "TXT-SUMMARY"
    assert provider.vendor == "demo"
    assert provider.priority == 100
    assert provider.extensions == (".txt",)
    assert provider.can_read is False
    assert provider.can_write is True
    assert provider.target == "shape"
    assert callable(provider._writer)


def test_formats_factory_single_provider(demo: ModuleType) -> None:
    providers = demo.formats()
    assert len(providers) == 1
    assert providers[0] is demo.TXT_SUMMARY_PROVIDER


def test_provider_field_completeness(demo: ModuleType) -> None:
    provider = demo.TXT_SUMMARY_PROVIDER
    names = {field.name for field in dataclass_fields(provider)}
    assert names == _PROVIDER_FIELDS
    assert isinstance(provider.can_read, bool)
    assert provider.target in {"shape", "xcaf"}
