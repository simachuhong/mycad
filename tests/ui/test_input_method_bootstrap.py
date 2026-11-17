# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Select the Fcitx portal only when the configured native Qt plugin is unusable."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from mycad.ui import input_method


@pytest.mark.parametrize("module", ["fcitx", "fcitx5"])
def test_uses_fcitx_portal_when_native_plugin_cannot_load(
    monkeypatch: pytest.MonkeyPatch, module: str
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("QT_IM_MODULE", module)
    monkeypatch.delenv("QT_IM_MODULES", raising=False)
    monkeypatch.delenv("IBUS_USE_PORTAL", raising=False)
    monkeypatch.setattr(input_method, "native_fcitx_available", lambda: False)
    monkeypatch.setattr(input_method, "fcitx_ibus_portal_available", lambda: True)
    monkeypatch.setattr(input_method, "bundled_ibus_available", lambda: True)
    prepared: list[bool] = []
    monkeypatch.setattr(input_method, "prefer_bundled_qt_plugins", lambda: prepared.append(True))
    input_method.prepare_input_method()
    assert os.environ["QT_IM_MODULE"] == "ibus"
    assert os.environ["IBUS_USE_PORTAL"] == "1"
    assert prepared == [True]


@pytest.mark.parametrize(
    ("module", "native", "portal", "modules", "platform"),
    [
        ("fcitx", True, True, None, "linux"),
        ("fcitx", False, False, None, "linux"),
        ("fcitx", False, True, "fcitx;ibus", "linux"),
        ("ibus", False, True, None, "linux"),
        ("fcitx", False, True, None, "win32"),
    ],
)
def test_preserves_other_input_method_choices(
    monkeypatch: pytest.MonkeyPatch,
    module: str,
    native: bool,
    portal: bool,
    modules: str | None,
    platform: str,
) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setenv("QT_IM_MODULE", module)
    if modules is None:
        monkeypatch.delenv("QT_IM_MODULES", raising=False)
    else:
        monkeypatch.setenv("QT_IM_MODULES", modules)
    monkeypatch.delenv("IBUS_USE_PORTAL", raising=False)
    monkeypatch.setattr(input_method, "native_fcitx_available", lambda: native)
    monkeypatch.setattr(input_method, "fcitx_ibus_portal_available", lambda: portal)
    monkeypatch.setattr(input_method, "bundled_ibus_available", lambda: True)
    prepared: list[bool] = []
    monkeypatch.setattr(input_method, "prefer_bundled_qt_plugins", lambda: prepared.append(True))
    input_method.prepare_input_method()
    assert os.environ["QT_IM_MODULE"] == module
    assert "IBUS_USE_PORTAL" not in os.environ
    assert not prepared


def test_does_not_switch_when_bundled_ibus_plugin_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("QT_IM_MODULE", "fcitx")
    monkeypatch.delenv("QT_IM_MODULES", raising=False)
    monkeypatch.delenv("IBUS_USE_PORTAL", raising=False)
    monkeypatch.setattr(input_method, "native_fcitx_available", lambda: False)
    monkeypatch.setattr(input_method, "fcitx_ibus_portal_available", lambda: True)
    monkeypatch.setattr(input_method, "bundled_ibus_available", lambda: False)
    input_method.prepare_input_method()
    assert os.environ["QT_IM_MODULE"] == "fcitx"
    assert "IBUS_USE_PORTAL" not in os.environ


@pytest.mark.skipif(
    os.environ.get("MYCAD_REAL_IME_TEST") != "1",
    reason="opt-in integration test needs Xvfb, D-Bus and Fcitx5 input methods",
)
@pytest.mark.parametrize("system_plugins", [False, True])
@pytest.mark.parametrize("method", ["pinyin", "wbpy"])
def test_real_fcitx_in_isolated_session(tmp_path: Path, system_plugins: bool, method: str) -> None:
    run_isolated_fcitx_probe(tmp_path, system_plugins=system_plugins, method=method)


@pytest.mark.skipif(
    os.environ.get("MYCAD_REAL_IME_TEST") != "1",
    reason="opt-in integration test needs Xvfb, D-Bus and Fcitx5 input methods",
)
def test_real_fcitx_through_gui_entry(tmp_path: Path) -> None:
    run_isolated_fcitx_probe(tmp_path, system_plugins=False, method="wbpy", full_startup=True)


def run_isolated_fcitx_probe(
    tmp_path: Path, *, system_plugins: bool, method: str, full_startup: bool = False
) -> None:
    if sys.platform != "linux" or any(
        shutil.which(command) is None
        for command in ("dbus-run-session", "xvfb-run", "fcitx5", "fcitx5-remote")
    ):
        pytest.skip("requires Linux, Xvfb, D-Bus and Fcitx5")
    system_path = Path("/usr/lib/x86_64-linux-gnu/qt6/plugins")
    if system_plugins and not (system_path / "platforminputcontexts").is_dir():
        pytest.skip("system Qt6 input method plugins are unavailable")
    if not (Path("/usr/share/fcitx5/inputmethod") / f"{method}.conf").is_file():
        pytest.skip(f"Fcitx input method {method} is unavailable")
    config = tmp_path / "config"
    profile = config / "fcitx5" / "profile"
    profile.parent.mkdir(parents=True)
    profile.write_text(
        f"[Groups/0]\nName=MyCAD test\nDefault Layout=us\nDefaultIM={method}\n\n"
        "[Groups/0/Items/0]\nName=keyboard-us\nLayout=\n\n"
        f"[Groups/0/Items/1]\nName={method}\nLayout=\n\n[GroupOrder]\n0=MyCAD test\n",
        encoding="utf-8",
    )
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    env = os.environ.copy()
    env.update(
        {
            "XDG_CONFIG_HOME": str(config),
            "XDG_DATA_HOME": str(tmp_path / "data"),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
            "XDG_RUNTIME_DIR": str(runtime),
            "XDG_SESSION_TYPE": "x11",
            "QT_QPA_PLATFORM": "xcb",
            "QT_IM_MODULE": "fcitx",
            "XMODIFIERS": "@im=fcitx",
            "NO_AT_BRIDGE": "1",
            "MYCAD_TEST_IME_METHOD": method,
            "MYCAD_TEST_FULL_STARTUP": "1" if full_startup else "0",
        }
    )
    for name in ("QT_IM_MODULES", "QT_PLUGIN_PATH", "IBUS_USE_PORTAL", "WAYLAND_DISPLAY"):
        env.pop(name, None)
    if system_plugins:
        env["QT_PLUGIN_PATH"] = str(system_path)
    probe = Path(__file__).with_name("fcitx_portal_probe.py")
    result = subprocess.run(
        ["dbus-run-session", "--", "xvfb-run", "-a", sys.executable, str(probe)],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-5000:]
