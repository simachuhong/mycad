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
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"

#: Single source of the forbidden import roots (F4 cites this constant by
#: name; no spelling variants are written anywhere else). Matching is
#: case-insensitive — the real PyPI name is RestrictedPython.
FORBIDDEN_IMPORT_ROOTS: frozenset[str] = frozenset(
    {
        # UI toolkits — phase 1. PySide6/shiboken6 are released from outright
        # ban by the src/mycad/ui/ carve-out (UI_ROOTS below); PySide2/PyQt5/
        # PyQt6/qtpy/vtk remain banned root-wide, and tkinter/wx close the
        # remaining toolkit back doors.
        "PySide6",
        "tkinter",
        "wx",
        "PySide2",
        "PyQt6",
        "PyQt5",
        "qtpy",
        "shiboken6",
        "vtk",
        # agent stack — phase 2; mcp and ollama are named by the plan
        "mcp",
        "ollama",
        "openai",
        "anthropic",
        "langchain",
        "litellm",
        # rival CAD bindings
        "cadquery",
        "OCC",
        "packaging",
        # network — the stdlib roots plus the third-party clients that reach
        # the closure through build123d's own dependencies
        "urllib",
        "urllib3",
        "requests",
        "httpx",
        "aiohttp",
        "ftplib",
        "http",
        "socket",
        "restrictedpython",
    }
)

#: CAD backends: allowed in the geom adapter package and nowhere else.
BACKEND_ROOTS: frozenset[str] = frozenset({"build123d", "OCP", "numpy"})
BACKEND_ALLOWED_PREFIX = "src/mycad/geom/"

#: UI stack: allowed only inside the src/mycad/ui/ carve-out. The roots
#: stay import-banned everywhere else, so no core/geom/app module can
#: reach Qt (the core Qt-free invariant is re-checked per file by
#: tests/core/test_signals.py).
UI_ROOTS: frozenset[str] = frozenset({"PySide6", "shiboken6"})
UI_ALLOWED_PREFIX = "src/mycad/ui/"

#: Distribution names banned from the runtime closure. Compared by EXACT
#: name: ``cadquery-ocp-novtk`` is required to be present, so a substring
#: test against "cadquery" would contradict the positive assertion below.
#: ``requests`` and ``urllib3`` are deliberately absent from this set —
#: both are transitive dependencies of the pinned build123d backend, so
#: banning them would mean dropping the backend. The enforceable rule is
#: that no MyCAD module imports them, which ``FORBIDDEN_IMPORT_ROOTS``
#: covers. ``pyside6``/``shiboken6`` are deliberately absent for the
#: same class of reason: phase 1 requires them in the closure, a
#: path-qualified allowance is impossible in a set of plain names, and
#: their imports stay confined to ``src/mycad/ui/`` via ``UI_ROOTS``.
FORBIDDEN_DISTRIBUTIONS: frozenset[str] = frozenset(
    {
        "pyside2",
        "pyqt6",
        "pyqt5",
        "vtk",
        "mcp",
        "ollama",
        "openai",
        "anthropic",
        "langchain",
        "litellm",
        "cadquery",
        "pythonocc-core",
        "packaging",
        "restrictedpython",
    }
)
REQUIRED_DISTRIBUTIONS: frozenset[str] = frozenset({"build123d", "cadquery-ocp-novtk"})

#: Commercial formats walled off by ADR-005, plus DWG. Matched as whole
#: words (case-insensitively) rather than as bare substrings: "sat"
#: occurs inside ordinary English words, but \b stops it matching
#: "saturate" while still catching a standalone token.
#: ``prt`` and ``asm`` are left out — as whole words they collide with
#: ordinary identifiers. ``nx`` is the one exception to case-folding:
#: lowercase ``nx``/``ny``/``nz`` are surface-normal components, so only
#: the uppercase vendor token ``NX`` counts (see ``_format_mentioned``).
COMMERCIAL_FORMATS: frozenset[str] = frozenset(
    {
        "jt",
        "parasolid",
        "acis",
        "sat",
        "sab",
        "x_t",
        "x_b",
        "sldprt",
        "nx",
        "catia",
        "catpart",
        "catproduct",
        "dwg",
    }
)

#: Stage-1+ concepts the plan forbids implementing in phase 0. Only
#: distinctive identifiers are listed: a negative "do not build X" rule
#: cannot be checked exhaustively, but a tripwire on the names such code
#: would inevitably use is far better than no assertion at all. Matched
#: case-insensitively as whole words. Each entry cites its Must-NOT item.
OUT_OF_SCOPE_CONCEPTS: tuple[tuple[str, str], ...] = (
    ("inverse_undo", "per-command inverse undo"),
    ("undo_inverse", "per-command inverse undo"),
    ("brep_snapshot", "BREP snapshot cache"),
    ("snapshot_cache", "BREP snapshot cache"),
    ("elementmap", "ElementMap / topological naming"),
    ("element_map", "ElementMap / topological naming"),
    ("constraintsolver", "sketch constraint solver"),
    ("constraint_solver", "sketch constraint solver"),
    ("solve_constraints", "sketch constraint solver"),
    ("igesprovider", "out-of-scope format provider"),
    ("gltfprovider", "out-of-scope format provider"),
    ("dxfprovider", "out-of-scope format provider"),
    ("threemfprovider", "out-of-scope format provider"),
    ("bill_of_materials", "PLM check-in/BOM"),
    ("checkout_part", "PLM check-in/BOM"),
    ("export_inp", "mesher / CAE solver"),
    ("cae_solver", "mesher / CAE solver"),
)

#: Build-host identifiers that must not appear in CI: phase 0 is T1 only.
FORBIDDEN_CI_TOKENS: tuple[str, ...] = ("aarch64", "arm64", "qemu", "loong")

#: Two Must-NOT items have no machine check, and that is deliberate rather
#: than a silent hole. The F1 coverage matrix owns them:
#:   M3 — the viewport stops at the tessellation data interface. That is a
#:        design boundary, not a token any grep can see.
#:   M7 — ``agent/`` stays protocol types plus Plan. "No product code yet"
#:        has no distinctive identifier to forbid.

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
            if module in UI_ROOTS and rel.startswith(UI_ALLOWED_PREFIX):
                continue
            if (
                module.lower() in lowered
                or module in BACKEND_ROOTS
                and not rel.startswith(BACKEND_ALLOWED_PREFIX)
            ):
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
    """Same detector as above, narrowed to its backend branch.

    Re-deriving the rule inline would let the two copies drift apart
    while the reverse self-proof only guards one of them.
    """
    offenders = [
        v for v in scan_forbidden_imports(SRC, REPO) if v.rsplit(":", 1)[1] in BACKEND_ROOTS
    ]
    assert offenders == []


def test_ui_imports_are_confined_to_the_ui_package(tmp_path: Path) -> None:
    """Same detector, narrowed to its UI branch: PySide6/shiboken6 may
    appear only under src/mycad/ui/, while tkinter stays banned even
    there — the carve-out releases exactly the two UI_ROOTS members.
    """
    ui = tmp_path / "src" / "mycad" / "ui"
    core = tmp_path / "src" / "mycad" / "core"
    ui.mkdir(parents=True)
    core.mkdir(parents=True)
    (ui / "window.py").write_text(
        "import PySide6\nfrom shiboken6 import Shiboken\n", encoding="utf-8"
    )
    (core / "leak.py").write_text("import PySide6\nimport tkinter\n", encoding="utf-8")
    found = scan_forbidden_imports(tmp_path, tmp_path)
    assert not any(v.startswith("src/mycad/ui/") for v in found), found
    assert any(v == "src/mycad/core/leak.py:1:PySide6" for v in found)
    assert any(v.endswith(":2:tkinter") for v in found)


# -- group 2: out-of-scope code ---------------------------------------------


def scan_out_of_scope(root: Path, repo: Path) -> list[str]:
    """Reserved command namespaces, stage-1 identifiers and commercial formats."""
    violations: list[str] = []
    for path in _python_files(root):
        rel = path.relative_to(repo).as_posix()
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        for namespace in ("view.", "sketch.", "datum."):
            # Either quote style: 'view.orbit' hid from a '"view.' needle.
            if f'"{namespace}' in text or f"'{namespace}" in text:
                violations.append(f"{rel}: reserved command namespace {namespace}")
        for identifier in OUT_OF_SCOPE_IDENTIFIERS:
            if identifier in text:
                violations.append(f"{rel}: stage-1 identifier {identifier}")
        if rel != STEP_READ_WHITELIST:
            for api in STEP_READ_APIS:
                if api in text:
                    violations.append(f"{rel}: STEP read API {api}")
        for fmt in COMMERCIAL_FORMATS:
            if _format_mentioned(fmt, text, lowered, path.stem.lower()):
                violations.append(f"{rel}: commercial format {fmt}")
        for concept, label in OUT_OF_SCOPE_CONCEPTS:
            if re.search(rf"\b{re.escape(concept)}\b", lowered):
                violations.append(f"{rel}: {label} ({concept})")
    return violations


def test_no_out_of_scope_code() -> None:
    assert scan_out_of_scope(SRC, REPO) == []


def test_no_out_of_scope_code_reverse_self_proof(tmp_path: Path) -> None:
    (tmp_path / "leak.py").write_text(
        "ID = 'view.orbit'\nPATH = \"part.sldprt\"\nERR = ImportSourceMissingError\n",
        encoding="utf-8",
    )
    found = scan_out_of_scope(tmp_path, tmp_path)
    assert any("reserved command namespace" in v for v in found)
    assert any("commercial format sldprt" in v for v in found)
    assert any("stage-1 identifier" in v for v in found)


def _format_mentioned(fmt: str, text: str, lowered: str, stem: str) -> bool:
    """Whether ``fmt`` shows up as its own token, or the file is named for it.

    ``nx`` is case-sensitive on purpose: ``nx, ny, nz = normal`` is
    geometry, not a Siemens NX adapter. CamelCase still hides a token —
    ``JTProvider`` has no word boundary — and that limit is asserted below.
    """
    if stem == fmt:
        return True
    if fmt == "nx":
        return re.search(r"\bNX\b", text) is not None
    return re.search(rf"\b{re.escape(fmt)}\b", lowered) is not None


def test_commercial_format_detector_catches_adapter_shaped_code(tmp_path: Path) -> None:
    """A quoted format token and a vendor name carry no dotted extension.

    ``class JTProvider`` alone is not caught: the token is glued to a
    suffix, so there is no word boundary. The ``("jt",)`` line is what
    this asserts, and the CamelCase file locks that limit in.
    """
    (tmp_path / "jt_adapter.py").write_text(
        'class JTProvider:\n    suffixes = ("jt",)\n', encoding="utf-8"
    )
    (tmp_path / "camel.py").write_text("class JTProvider:\n    pass\n", encoding="utf-8")
    (tmp_path / "xt_io.py").write_text("PK_BODY = 'parasolid handle'\n", encoding="utf-8")
    (tmp_path / "dwg_io.py").write_text('SUFFIX = "dwg"\n', encoding="utf-8")
    found = scan_out_of_scope(tmp_path, tmp_path)
    for needle in ("commercial format jt", "commercial format parasolid", "commercial format dwg"):
        assert any(needle in v for v in found), f"{needle} escaped the detector"
    assert not any(v.startswith("camel.py") for v in found)


def test_surface_normal_components_are_not_the_nx_format(tmp_path: Path) -> None:
    (tmp_path / "normals.py").write_text("nx, ny, nz = 0.0, 0.0, 1.0\n", encoding="utf-8")
    (tmp_path / "vendor.py").write_text("backend = 'NX'\n", encoding="utf-8")
    found = scan_out_of_scope(tmp_path, tmp_path)
    assert not any(v.startswith("normals.py") for v in found)
    assert any(v.startswith("vendor.py") and "commercial format nx" in v for v in found)


def test_out_of_scope_concept_detector_reverse_self_proof(tmp_path: Path) -> None:
    (tmp_path / "leak.py").write_text(
        "class ElementMap:\n    pass\n\n\ndef solve_constraints():\n    pass\n", encoding="utf-8"
    )
    found = scan_out_of_scope(tmp_path, tmp_path)
    assert any("ElementMap / topological naming" in v for v in found)
    assert any("sketch constraint solver" in v for v in found)


def test_step_read_whitelist_branch_is_live(tmp_path: Path) -> None:
    """The whitelist must be the only thing exempting a STEP read API.

    ``test_no_out_of_scope_code`` only scans ``src/``, where the
    whitelisted path can never appear, so without this the branch could
    be widened to ``tests/`` and nothing would go red.
    """
    helper = tmp_path / STEP_READ_WHITELIST
    helper.parent.mkdir(parents=True)
    body = f"x = {STEP_READ_APIS[0]}\n"
    helper.write_text(body, encoding="utf-8")
    (tmp_path / "elsewhere.py").write_text(body, encoding="utf-8")
    found = scan_out_of_scope(tmp_path, tmp_path)
    assert any(v.startswith("elsewhere.py: STEP read API") for v in found)
    assert not any(v.startswith(STEP_READ_WHITELIST) for v in found)


def test_no_out_of_scope_modules_or_directories() -> None:
    for banned in ("schema_tools", "schema_catalog", "tool_schema"):
        assert list(REPO.glob(f"**/{banned}.py")) == []
    assert not (REPO / "tests" / "snapshots").exists()


#: Installer/bundler artefacts. ``msi`` is named by the plan; ``wxs``
#: is the WiX source that produces one.
PACKAGING_PATTERNS: tuple[str, ...] = (
    "*.spec",
    "*.nsi",
    "*.iss",
    "*.AppImage",
    "*flatpak*",
    "*.msi",
    "*.wxs",
    "*.deb",
    "*.rpm",
)

SKIPPED_TREE_PARTS = frozenset({".venv", ".git", ".omo", ".ruff_cache", ".pytest_cache"})


def scan_packaging_config(root: Path) -> list[str]:
    """Installer/bundler files anywhere in the tree, not just at the root."""
    return sorted(
        p.relative_to(root).as_posix()
        for pattern in PACKAGING_PATTERNS
        for p in root.rglob(pattern)
        if not (SKIPPED_TREE_PARTS & set(p.parts))
    )


def test_no_network_or_packaging_config() -> None:
    """No installer/bundler configuration: distribution is out of scope."""
    assert scan_packaging_config(REPO) == []


def test_no_network_or_packaging_config_reverse_self_proof(tmp_path: Path) -> None:
    nested = tmp_path / "packaging" / "linux"
    nested.mkdir(parents=True)
    (nested / "mycad.spec").touch()
    assert scan_packaging_config(tmp_path) == ["packaging/linux/mycad.spec"]


def test_ci_has_no_out_of_tier_runners() -> None:
    """Phase 0 CI is T1 only: no aarch64, QEMU or LoongArch jobs (ADR-006)."""
    text = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8").lower()
    assert [token for token in FORBIDDEN_CI_TOKENS if token in text] == []


def test_src_uses_pathlib_not_hardcoded_separators() -> None:
    """Paths are pathlib everywhere: no ``os.sep`` and no ``os.path.join``."""
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
    # uv emits UTF-8 regardless of locale; Windows text=True defaults to
    # cp1252 and mojibakes the tree glyphs into the parsed closure.
    result = subprocess.run(
        UV_TREE_COMMAND,
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    # Not a skip: a skip here would retire the whole closure assertion the
    # moment uv went missing from a runner, and nothing would say so.
    assert result.returncode == 0, f"uv tree failed: {result.stderr.strip()[:200]}"
    closure = parse_closure(result.stdout)
    assert FORBIDDEN_DISTRIBUTIONS & closure == set()
    assert closure >= REQUIRED_DISTRIBUTIONS


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
    # git emits raw UTF-8 path bytes; the Windows cp1252 default decode dies
    # inside the reader thread on non-ASCII names, leaving stdout None.
    listing = subprocess.run(
        ("git", "ls-files", "-z", "docs/"),
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
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
