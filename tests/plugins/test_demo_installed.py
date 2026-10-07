# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Real-installation tests for the demo plugin (T9c) — the only place
that runs pip (#round9-6 / #round11-NB6).

Install discipline: the current interpreter (the CI job's uv venv) first
runs ``ensurepip --upgrade`` (uv-managed venvs often ship without pip;
idempotent), then ``pip install -e`` the plugin with
``--no-build-isolation`` (hatchling/editables come from the main repo's
dev extra). Teardown uninstalls and asserts no importable residue.
Every assertion runs in a child process (``sys.executable -c``) so the
test process never imports the demo package.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import cast

import pytest

from mycad.builtin_commands import BUILTIN_COMMAND_SPECS

#: tests/plugins/test_demo_installed.py -> parents[2] is the repository root.
REPO_ROOT: Path = Path(__file__).resolve().parents[2]
DEMO_DIR: Path = REPO_ROOT / "plugins_examples" / "mycad_plugin_demo"
BUILTIN_IDS: tuple[str, ...] = tuple(spec.id for spec in BUILTIN_COMMAND_SPECS)

#: Exit 0 only when the demo package is no longer importable.
_RESIDUAL_PROBE = (
    "import importlib.util; "
    "raise SystemExit(0 if importlib.util.find_spec('mycad_plugin_demo') is None else 1)"
)

#: Example ①: registry state after install — demo.ping in, builtins intact.
_PROBE_REGISTRY = """\
import json
from mycad.app import build_app
services = build_app()
demo_hits = sorted(spec.id for spec in services.registry.search("demo.ping"))
all_ids = sorted(
    spec.id for group in services.registry.list_by_category().values() for spec in group
)
print(json.dumps({"demo_hits": demo_hits, "all_ids": all_ids}))
"""

#: Example ②: bus.execute through the plugin's handler factory.
_PROBE_EXECUTE = """\
import json
from mycad.app import build_app, new_document
services = build_app()
loaded = new_document(services)
result = loaded.bus.execute("demo.ping", {})
print(json.dumps({"result": result}))
"""

#: Example ③: TXT-SUMMARY resolves and actually writes a summary file.
_PROBE_FORMAT = """\
import json
import tempfile
from pathlib import Path
from mycad.app import build_app, new_document
from mycad.core.ports import FormatPort
services = build_app()
loaded = new_document(services)
loaded.bus.execute("feature.box", {"size_x": 2.0, "size_y": 3.0, "size_z": 4.0})
path = Path(tempfile.mkdtemp()) / "x.txt"
port = services.formats.resolve(path)
is_port = isinstance(port, FormatPort)
port.write(services.kernel, path)
content = path.read_text(encoding="utf-8")
print(json.dumps({"is_format_port": is_port, "name": port.name, "content": content}))
"""

#: Example ④: two build_app() calls produce identical discovery lists.
_PROBE_DETERMINISM = """\
import json
from mycad.app import build_app
def snapshot(services):
    return {
        "commands": sorted(c.spec.id for c in services.plugins.command_contributions()),
        "providers": sorted(p.name for p in services.plugins.format_providers()),
        "distributions": [p.distribution_name for p in services.plugins.discovered_plugins],
    }
first = snapshot(build_app())
second = snapshot(build_app())
print(json.dumps({"first": first, "second": second, "equal": first == second}))
"""

#: Manifest visibility through the plugin manager.
_PROBE_MANIFEST = """\
import json
from mycad.app import build_app
services = build_app()
plugins = services.plugins.discovered_plugins
payload = {
    "count": len(plugins),
    "manifests": [
        {
            "id": p.manifest.id,
            "version": p.manifest.version,
            "api_version": p.manifest.api_version,
            "permissions": list(p.manifest.permissions),
            "homepage": p.manifest.homepage,
        }
        for p in plugins
        if p.manifest is not None
    ],
    "warnings": [list(p.warnings) for p in plugins],
}
print(json.dumps(payload))
"""

#: Example ⑤: after uninstall, discovery falls back to zero plugins.
_PROBE_EMPTY = """\
import json
from mycad.app import build_app
services = build_app()
payload = {
    "demo_hits": [spec.id for spec in services.registry.search("demo.ping")],
    "contributions": [c.spec.id for c in services.plugins.command_contributions()],
    "providers": [p.name for p in services.plugins.format_providers()],
}
print(json.dumps(payload))
"""


def _run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run one child of the current interpreter from the repository root."""

    return subprocess.run(
        [sys.executable, *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def _probe_json(code: str) -> dict[str, object]:
    """Run a child-process probe and parse its single JSON output line."""

    proc = _run(("-c", code))
    assert proc.returncode == 0, f"probe exited {proc.returncode}: {proc.stderr}"
    stdout = proc.stdout
    assert stdout is not None
    payload: dict[str, object] = json.loads(stdout)
    return payload


@pytest.fixture(scope="session")
def ensure_pip() -> None:
    """Make sure pip exists in the uv-managed venv (idempotent upgrade)."""

    proc = _run(("-m", "ensurepip", "--upgrade"))
    if proc.returncode != 0:
        pytest.fail(f"ensurepip failed ({proc.returncode}): {proc.stderr}")


@pytest.fixture(scope="class")
def demo_installed(ensure_pip: None) -> Iterator[None]:
    """Editable-install the demo plugin for one class; uninstall afterwards."""

    install = _run(("-m", "pip", "install", "-e", str(DEMO_DIR), "--no-build-isolation", "--quiet"))
    if install.returncode != 0:
        pytest.fail(f"pip install -e failed ({install.returncode}): {install.stderr}")
    try:
        yield
    finally:
        uninstall = _run(("-m", "pip", "uninstall", "-y", "mycad-plugin-demo", "--quiet"))
        if uninstall.returncode != 0:
            pytest.fail(f"pip uninstall failed ({uninstall.returncode}): {uninstall.stderr}")
        residual = _run(("-c", _RESIDUAL_PROBE))
        if residual.returncode != 0:
            pytest.fail("mycad_plugin_demo still importable after uninstall")


class TestInstalledDemo:
    """Examples ①-④ and the manifest-visibility probe, all while installed."""

    def test_demo_command_discovered_with_builtins_intact(self, demo_installed: None) -> None:
        payload = _probe_json(_PROBE_REGISTRY)
        assert payload["demo_hits"] == ["demo.ping"]
        all_ids = cast("list[str]", payload["all_ids"])
        assert "demo.ping" in all_ids
        assert set(BUILTIN_IDS) <= set(all_ids)
        assert len(all_ids) == len(BUILTIN_IDS) + 1

    def test_bus_execute_demo_ping_returns_pong(self, demo_installed: None) -> None:
        payload = _probe_json(_PROBE_EXECUTE)
        assert payload["result"] == "pong"

    def test_txt_summary_resolves_and_writes_file(self, demo_installed: None) -> None:
        payload = _probe_json(_PROBE_FORMAT)
        assert payload["is_format_port"] is True
        assert payload["name"] == "TXT-SUMMARY"
        content = payload["content"]
        assert isinstance(content, str)
        assert "solids=1" in content
        assert "volume" in content

    def test_two_build_app_calls_discover_identically(self, demo_installed: None) -> None:
        payload = _probe_json(_PROBE_DETERMINISM)
        assert payload["equal"] is True
        first = cast("dict[str, object]", payload["first"])
        assert first["commands"] == ["demo.ping"]
        assert first["providers"] == ["TXT-SUMMARY"]
        assert first["distributions"] == ["mycad-plugin-demo"]

    def test_manifest_visible_through_plugin_manager(self, demo_installed: None) -> None:
        payload = _probe_json(_PROBE_MANIFEST)
        assert payload["count"] == 1
        manifests = cast("list[dict[str, object]]", payload["manifests"])
        assert len(manifests) == 1
        manifest = manifests[0]
        assert manifest["id"] == "mycad-plugin-demo"
        assert manifest["version"] == "0.1.0"
        assert manifest["api_version"] == "1.0"
        assert manifest["permissions"] == []
        assert manifest["homepage"] == ""
        assert payload["warnings"] == [[]]


class TestAfterUninstall:
    """Example ⑤, deliberately last: runs after the class fixture's teardown."""

    def test_discovery_restored_to_zero_plugins(self) -> None:
        payload = _probe_json(_PROBE_EMPTY)
        assert payload["demo_hits"] == []
        assert payload["contributions"] == []
        assert payload["providers"] == []
        residual = _run(("-c", _RESIDUAL_PROBE))
        assert residual.returncode == 0
