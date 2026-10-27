# P2-25 — Headless and desktop dependency boundary

Date: 2026-10-24

## Changes

- The default runtime keeps `build123d==0.11.1` and `cadquery-ocp-novtk>=7.9.3.1.1,<7.9.4`; only PySide6, pyqtgraph, and PyOpenGL moved to the `desktop` extra. No geometry pin changed.
- `mycad gui` now turns a missing Qt/GL module into an actionable `uv sync --extra desktop` hint and exit code 1; ordinary CLI imports remain headless.
- The CI quality matrix installs `--extra desktop`. A separate Ubuntu 22.04 job installs only `--no-dev` and runs `scripts/verify_headless_install.py`, which checks the missing-GUI hint and runs the flange plan into temporary STEP, STL, and `.mc.json` outputs.
- README, AGENTS.md, ADR-006, and NOTICE describe the two installation shapes. NOTICE covers the 56-distribution all-platform union with all extras. The dependency audit uses `uv export`; `uv tree` from the installed lock graph includes optional extras and cannot distinguish the default closure in this uv version.

## Verification

```text
uv lock --check
Resolved 72 packages in 4ms

uv run pytest tests/cli/test_optional_desktop.py tests/test_notice.py tests/test_adr_docs.py tests/test_scope_audit.py -q
50 passed in 62.11s

uv run ruff check scripts/verify_headless_install.py tests/cli/test_optional_desktop.py tests/test_notice.py tests/test_scope_audit.py tests/test_adr_docs.py src/mycad/cli/__main__.py src/mycad/ui/main_window.py
All checks passed!
uv run ruff format --check scripts/verify_headless_install.py tests/cli/test_optional_desktop.py tests/test_notice.py tests/test_scope_audit.py tests/test_adr_docs.py src/mycad/cli/__main__.py src/mycad/ui/main_window.py
7 files already formatted
uv run basedpyright scripts/verify_headless_install.py tests/cli/test_optional_desktop.py tests/test_notice.py tests/test_scope_audit.py tests/test_adr_docs.py src/mycad/cli/__main__.py src/mycad/ui/main_window.py
0 errors, 0 warnings, 0 notes
```

Fresh environments were installed from the frozen lock:

- `UV_PROJECT_ENVIRONMENT=/tmp/mycad-p2-25-headless uv sync --frozen --no-dev` — 47 packages; no PySide6, pyqtgraph, PyOpenGL, or shiboken6.
- `UV_PROJECT_ENVIRONMENT=/tmp/mycad-p2-25-desktop uv sync --frozen --no-dev --extra desktop` — 55 packages; all four desktop modules imported successfully.
- `UV_PROJECT_ENVIRONMENT=/tmp/mycad-p2-25-headless uv run --no-sync python scripts/verify_headless_install.py` — passed; installed CLI validated and executed the flange plan, and produced all three non-empty outputs in a temporary directory.

## Coverage limits

Clean installation was performed on Ubuntu x86-64 / Python 3.12.3 / glibc 2.39. It does not establish a native aarch64 install. T2 remains an expected wheel-compatible headless shape, with desktop wheel floor glibc 2.39 as documented in ADR-006.
