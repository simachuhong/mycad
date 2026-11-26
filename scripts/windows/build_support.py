# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Prepare reproducible Windows resources and evidence from installed packages."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
import shutil
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path


def read_version(root: Path, revision: int) -> str:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = str(project["version"])
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Windows packaging requires a three-component numeric project version")
    numbers = [*(int(part) for part in version.split(".")), revision]
    if any(part < 0 or part > 65535 for part in numbers):
        raise ValueError("Windows version components must be between 0 and 65535")
    return ".".join(map(str, numbers))


def prepare(root: Path, output: Path, revision: int) -> None:
    version = read_version(root, revision)
    output.mkdir(parents=True, exist_ok=True)
    payload = output / "payload"
    payload.mkdir(exist_ok=True)
    for name in ("LICENSE", "NOTICE"):
        shutil.copy2(root / name, payload / name)
    shutil.copy2(root / "docs/windows-installer-testing.md", payload / "Windows-testing.md")
    licenses = payload / "third-party-licenses"
    licenses.mkdir(exist_ok=True)
    shutil.copytree(
        root / "scripts/windows/licenses", licenses / "supplemental", dirs_exist_ok=True
    )
    packages: list[dict[str, object]] = []
    for distribution in sorted(
        importlib.metadata.distributions(), key=lambda item: item.metadata["Name"].lower()
    ):
        name = distribution.metadata["Name"]
        copied: list[str] = []
        for item in distribution.files or ():
            # Do not flatten license trees: distinct files can have the same basename.
            if any(
                part.lower().startswith(("license", "licence", "copying", "notice"))
                for part in item.parts
            ):
                source = Path(str(distribution.locate_file(item)))
                if source.is_file():
                    safe_parts = [part for part in item.parts if part not in ("..", ".")]
                    destination = licenses / name / Path(*safe_parts)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
                    copied.append(destination.relative_to(payload).as_posix())
        packages.append({"name": name, "version": distribution.version, "license_files": copied})
    missing = [item["name"] for item in packages if not item["license_files"]]
    (licenses / "audit.json").write_text(
        json.dumps(
            {
                "installed_distributions": packages,
                "no_bundled_license_found": missing,
                "status": "Inventory only; review NOTICE and native-library redistribution separately.",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, encoding="utf-8", capture_output=True, check=True
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        encoding="utf-8",
        capture_output=True,
        check=True,
    ).stdout
    info = {
        "version": version,
        "commit": commit,
        "dirty": bool(dirty.strip()),
        "working_tree_changes": dirty.splitlines(),
        "python": sys.version,
        "platform": platform.platform(),
        "created_utc": datetime.now(UTC).isoformat(),
        "distributions": packages,
        "runtime_lock_sha256": hashlib.sha256((root / "uv.lock").read_bytes()).hexdigest(),
        "windows_validation": "pending",
        "signed": False,
    }
    for destination in (output / "build-info.json", payload / "build-info.json"):
        destination.write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", "utf-8")
    (output / "version.txt").write_text(version, encoding="ascii")
    numeric = tuple(int(part) for part in version.split("."))
    (output / "version-resource.txt").write_text(
        f"VSVersionInfo(ffi=FixedFileInfo(filevers={numeric!r}, prodvers={numeric!r}, "
        "mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0,0)), "
        "kids=[StringFileInfo([StringTable('040904B0', ["
        "StringStruct('CompanyName', 'MyCAD contributors'),"
        "StringStruct('ProductName', 'MyCAD'),"
        "StringStruct('FileDescription', 'MyCAD Desktop'),"
        f"StringStruct('FileVersion', '{version}'),"
        f"StringStruct('ProductVersion', '{version}'),"
        "StringStruct('LegalCopyright', 'Copyright 2026 MyCAD contributors')"
        "])]), VarFileInfo([VarStruct('Translation', [1033,1200])])])\n",
        encoding="utf-8",
    )


def finalize(output: Path) -> None:
    installers = sorted(output.glob("MyCAD-*-x64-Setup.exe"))
    if not installers:
        raise FileNotFoundError("No installer was generated; refusing to write checksums")
    entries: list[dict[str, object]] = []
    sums: list[str] = []
    for installer in installers:
        with installer.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        entries.append(
            {"name": installer.name, "sha256": digest, "bytes": installer.stat().st_size}
        )
        sums.append(f"{digest}  {installer.name}\n")
    path = output / "build-info.json"
    info = json.loads(path.read_text(encoding="utf-8"))
    info["installers"] = entries
    path.write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", "utf-8")
    (output / "SHA256SUMS").write_text("".join(sums), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--revision", type=int, default=0)
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    if args.finalize:
        finalize(args.output)
    else:
        prepare(args.root, args.output, args.revision)
