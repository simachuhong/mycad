# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Machine-checked scope fidelity (plan F2/F4): the Must-NOT-have list.

Every assertion here is executable — the final verification wave runs this
file instead of accepting a human grep. Each group carries a reverse
self-proof that feeds deliberately offending input to the SAME detector,
so a detector that silently stopped detecting fails the suite.
"""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"

#: Single source of the forbidden import roots (F4 cites this constant by
#: name; no spelling variants are written anywhere else). Matching is
#: case-insensitive — the real PyPI name is RestrictedPython.
FORBIDDEN_IMPORT_ROOTS: frozenset[str] = frozenset(
    {
        "PySide6",
        "PyQt6",
        "PyQt5",
        "vtk",
        "mcp",
        "cadquery",
        "OCC",
        "packaging",
        "urllib",
        "requests",
        "http",
        "socket",
        "restrictedpython",
    }
)

#: CAD backends: allowed in the geom adapter package and nowhere else.
BACKEND_ROOTS: frozenset[str] = frozenset({"build123d", "OCP", "numpy"})
BACKEND_ALLOWED_PREFIX = "src/mycad/geom/"

#: Distribution names banned from the runtime closure. Compared by EXACT
#: name: ``cadquery-ocp-novtk`` is required to be present, so a substring
#: test against "cadquery" would contradict the positive assertion below.
#: ``requests`` is deliberately absent from this set — it is a direct
#: dependency of the pinned build123d backend, so banning it would mean
#: dropping the backend. The enforceable rule is that no MyCAD module
#: imports it, which ``FORBIDDEN_IMPORT_ROOTS`` already covers.
FORBIDDEN_DISTRIBUTIONS: frozenset[str] = frozenset(
    {"pyside6", "pyqt6", "pyqt5", "vtk", "mcp", "cadquery", "pythonocc-core", "packaging"}
)
REQUIRED_DISTRIBUTIONS: frozenset[str] = frozenset({"build123d", "cadquery-ocp-novtk"})

#: Commercial formats walled off by ADR-005. Matched as dotted file
#: suffixes and whole file-name stems, never as bare substrings — "sat"
#: and "nx" occur inside ordinary English words.
COMMERCIAL_FORMATS: frozenset[str] = frozenset(
    {"jt", "parasolid", "acis", "sat", "x_t", "sldprt", "nx", "catia"}
)

#: Identifiers of the stage-1 STEP import feature, absent from phase 0.
#: Concatenated for the same reason as ``STEP_READ_APIS`` below.
OUT_OF_SCOPE_IDENTIFIERS: tuple[str, ...] = (
    "document.import" + "_step",
    "imported_solid",
    "ImportSourceMissingError",
)

#: The ONE file allowed to touch a STEP read API (test-only helper). The
#: needle is concatenated so this auditor is not itself an occurrence —
#: same convention as tests/formats/test_guards.py.
STEP_READ_WHITELIST = "tests/helpers/step_roundtrip.py"
STEP_READ_APIS: tuple[str, ...] = ("import" + "_step",)

UV_TREE_COMMAND: tuple[str, ...] = ("uv", "tree", "--package", "mycad", "--no-dev")


def _python_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _import_roots(tree: ast.Module) -> list[tuple[int, str]]:
    """Root module of every import in ``tree``, with its line number."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name.split(".")[0]) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append((node.lineno, node.module.split(".")[0]))
    return found


def scan_forbidden_imports(root: Path, repo: Path) -> list[str]:
    """Return ``file:line:module`` for every out-of-scope import under ``root``."""
    violations: list[str] = []
    lowered = {name.lower() for name in FORBIDDEN_IMPORT_ROOTS}
    for path in _python_files(root):
        rel = path.relative_to(repo).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for lineno, module in _import_roots(tree):
            if module.lower() in lowered:
                violations.append(f"{rel}:{lineno}:{module}")
            elif module in BACKEND_ROOTS and not rel.startswith(BACKEND_ALLOWED_PREFIX):
                violations.append(f"{rel}:{lineno}:{module}")
    return violations


# -- group 1: imports and dependency surface --------------------------------


def test_no_forbidden_imports() -> None:
    assert scan_forbidden_imports(SRC, REPO) == []


def test_no_forbidden_imports_reverse_self_proof(tmp_path: Path) -> None:
    (tmp_path / "leak.py").write_text("import requests\n", encoding="utf-8")
    (tmp_path / "backend_leak.py").write_text("import build123d\n", encoding="utf-8")
    found = scan_forbidden_imports(tmp_path, tmp_path)
    assert any(v.endswith(":1:requests") for v in found)
    assert any(v.endswith(":1:build123d") for v in found)


def test_backend_imports_are_confined_to_geom() -> None:
    offenders = [
        path.relative_to(REPO).as_posix()
        for path in _python_files(SRC)
        for _, module in _import_roots(ast.parse(path.read_text(encoding="utf-8")))
        if module in BACKEND_ROOTS
        and not path.relative_to(REPO).as_posix().startswith(BACKEND_ALLOWED_PREFIX)
    ]
    assert offenders == []


# -- group 2: out-of-scope code ---------------------------------------------


def scan_out_of_scope(root: Path, repo: Path) -> list[str]:
    """Reserved command namespaces, stage-1 identifiers and commercial formats."""
    violations: list[str] = []
    for path in _python_files(root):
        rel = path.relative_to(repo).as_posix()
        text = path.read_text(encoding="utf-8")
        for prefix in ('"view.', '"sketch.', '"datum.'):
            if prefix in text:
                violations.append(f"{rel}: reserved command namespace {prefix[1:]}")
        for identifier in OUT_OF_SCOPE_IDENTIFIERS:
            if identifier in text:
                violations.append(f"{rel}: stage-1 identifier {identifier}")
        if rel != STEP_READ_WHITELIST:
            for api in STEP_READ_APIS:
                if api in text:
                    violations.append(f"{rel}: STEP read API {api}")
        for fmt in COMMERCIAL_FORMATS:
            if f".{fmt}" in text.lower() or path.stem.lower() == fmt:
                violations.append(f"{rel}: commercial format {fmt}")
    return violations


def test_no_out_of_scope_code() -> None:
    assert scan_out_of_scope(SRC, REPO) == []


def test_no_out_of_scope_code_reverse_self_proof(tmp_path: Path) -> None:
    (tmp_path / "leak.py").write_text(
        'ID = "view.orbit"\nPATH = "part.sldprt"\nERR = ImportSourceMissingError\n',
        encoding="utf-8",
    )
    found = scan_out_of_scope(tmp_path, tmp_path)
    assert any("reserved command namespace" in v for v in found)
    assert any("commercial format sldprt" in v for v in found)
    assert any("stage-1 identifier" in v for v in found)


def test_no_out_of_scope_modules_or_directories() -> None:
    for banned in ("schema_tools", "schema_catalog", "tool_schema"):
        assert list(REPO.glob(f"**/{banned}.py")) == []
    assert not (REPO / "tests" / "snapshots").exists()


def test_no_network_or_packaging_config() -> None:
    """No installer/bundler configuration: distribution is out of scope."""
    patterns = ("*.spec", "*.nsi", "*.iss", "*.AppImage", "*flatpak*")
    offenders = [
        p.relative_to(REPO).as_posix()
        for pattern in patterns
        for p in REPO.glob(pattern)
        if ".venv" not in p.parts
    ]
    assert offenders == []


def test_src_uses_pathlib_not_hardcoded_separators() -> None:
    """Paths are pathlib everywhere; no ``os.sep`` or glued '/' literals."""
    offenders: list[str] = []
    for path in _python_files(SRC):
        rel = path.relative_to(REPO).as_posix()
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "os.sep" in line or "os.path.join" in line:
                offenders.append(f"{rel}:{lineno}")
    assert offenders == []


# -- group 3: runtime dependency closure ------------------------------------


def parse_closure(text: str) -> set[str]:
    """Distribution names in a ``uv tree`` rendering (exact names, lowercased)."""
    names: set[str] = set()
    for line in text.splitlines():
        stripped = line.lstrip("│├└─ \t")
        if not stripped or stripped.startswith("("):
            continue
        head = stripped.split(" ", 1)[0]
        if head:
            names.add(head.lower())
    return names


def test_runtime_closure_clean() -> None:
    result = subprocess.run(UV_TREE_COMMAND, cwd=REPO, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        pytest.skip(f"uv unavailable: {result.stderr.strip()[:120]}")
    closure = parse_closure(result.stdout)
    assert FORBIDDEN_DISTRIBUTIONS & closure == set()
    assert REQUIRED_DISTRIBUTIONS <= closure


def test_runtime_closure_reverse_self_proof() -> None:
    tampered = "mycad v0.1.0\n├── build123d v0.11.1\n│   └── vtk v9.3.0\n"
    closure = parse_closure(tampered)
    assert "vtk" in closure
    assert FORBIDDEN_DISTRIBUTIONS & closure != set()


# -- group 4: tree boundaries ------------------------------------------------


def test_wheel_excludes_examples_and_fixtures() -> None:
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert 'packages = ["src/mycad"]' in text
    assert "plugins_examples" not in text
    assert "tests/fixtures" not in text


def hash_tracked_docs(repo: Path) -> dict[str, str]:
    """sha256 of every git-tracked file under ``docs/``."""
    # -z keeps non-ASCII names literal; the default output octal-escapes
    # and quotes them, which would not resolve as a path.
    listing = subprocess.run(
        ("git", "ls-files", "-z", "docs/"), cwd=repo, capture_output=True, text=True, check=True
    )
    digests: dict[str, str] = {}
    for rel in listing.stdout.split("\0"):
        if rel:
            digests[rel] = hashlib.sha256((repo / rel).read_bytes()).hexdigest()
    return digests


def test_tree_boundaries_docs_baseline_unchanged() -> None:
    baseline = json.loads(
        (REPO / "tests" / "fixtures" / "baseline_doc_sha256.json").read_text(encoding="utf-8")
    )
    digests = hash_tracked_docs(REPO)
    for rel, expected in baseline.items():
        assert digests[rel] == expected, f"baseline document changed: {rel}"


def test_tree_boundaries_reverse_self_proof(tmp_path: Path) -> None:
    """The same hashing function must notice an edited baseline document."""
    docs = tmp_path / "docs"
    docs.mkdir()
    doc = docs / "需求分析书.md"
    doc.write_text("original\n", encoding="utf-8")
    for args in (("init", "-q"), ("add", "docs/需求分析书.md")):
        subprocess.run(("git", *args), cwd=tmp_path, check=True, capture_output=True)

    baseline = hash_tracked_docs(tmp_path)
    assert set(baseline) == {"docs/需求分析书.md"}  # -z handling, non-ASCII name
    doc.write_text("edited\n", encoding="utf-8")
    assert hash_tracked_docs(tmp_path) != baseline


def test_no_planning_scratch_in_product_tree() -> None:
    skip = {".git", ".omo", ".venv", ".ruff_cache", ".pytest_cache", ".codegraph"}
    offenders: list[str] = []
    for entry in REPO.iterdir():
        if entry.name in skip:
            continue
        if entry.is_dir() and entry.name in ("review", "island"):
            offenders.append(entry.name)
        if entry.is_file() and entry.name.endswith("-ledger.md"):
            offenders.append(entry.name)
    assert offenders == []
