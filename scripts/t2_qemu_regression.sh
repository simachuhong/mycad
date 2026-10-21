#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
#T2 aarch64 regression under QEMU (todo 15, ADR-006 §2 close-out).
#
#Route decision (recorded in .omo/evidence/t2-qemu-regression-phase1-desktop-shell.md):
#docker --platform linux/arm64 over qemu-user binfmt handlers, NOT
#qemu-system + a cloud image. Rationale: no full-machine boot, reproducible via
#a pinned multi-arch base image, and the workloads under test (uv resolution,
#wheel install, pytest) are process-level, so qemu-user semantics suffice.
#
#What it proves inside an emulated aarch64 container:
#  1. Python 3.12 on aarch64 (manylinux wheels resolve).
#  2. `uv sync --frozen` installs the pinned dependency closure — in particular
#     PySide6, build123d and cadquery-ocp-novtk must publish manylinux aarch64
#     wheels (ADR-006 T2 premise).
#  3. The test-suite subset given in T2_PYTEST_ARGS actually passes offscreen.
#
#Usage:
#  scripts/t2_qemu_regression.sh            # full run (sync + pytest)
#  T2_SKIP_SYNC=1 scripts/...               # reuse an existing running venv
#Environment overrides: T2_IMAGE (base image), T2_TIMEOUT (seconds), T2_REPO
#(mounted repo, defaults to the script's parent), T2_LOG_DIR (log target),
#UV_DEFAULT_INDEX (PyPI mirror for restricted networks).
set -uo pipefail

REPO="${T2_REPO:-$(cd "$(dirname "$0")/.." && pwd)}"
# Default = ubuntu:24.04 (glibc 2.39): the pinned PySide6 6.12.0 publishes
# aarch64 wheels only as manylinux_2_39 — see the evidence file. Debian
# bookworm (glibc 2.36) is a documented opt-in probe that must fail stage 3.
IMAGE="${T2_IMAGE:-mycad-t2-arm64:latest}"
LOG_DIR="${T2_LOG_DIR:-/tmp/opencode}"
TIMEOUT="${T2_TIMEOUT:-3600}"
PYTEST_ARGS="${T2_PYTEST_ARGS:--q}"

mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/t2-qemu-regression.log"
: >"$LOG"

echo "T2 aarch64 QEMU regression — repo=$REPO image=$IMAGE timeout=${TIMEOUT}s"
echo "pytest args: $PYTEST_ARGS"
echo "target arch: linux/arm64 (qemu-user via docker binfmt)"

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "prep image $IMAGE not found; building from scripts/t2/Dockerfile ..."
  docker build --platform linux/arm64 -t "$IMAGE" -f scripts/t2/Dockerfile .
fi

docker run --rm -i --platform linux/arm64 \
  --env UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX:-}" \
  --env UV_PROJECT_ENVIRONMENT="${LOG_DIR}/arm-venv" \
  --env UV_CACHE_DIR="${LOG_DIR}/uv-cache" \
  --env QT_QPA_PLATFORM=offscreen \
  --env LIBGL_ALWAYS_SOFTWARE="${LIBGL_ALWAYS_SOFTWARE:-1}" \
  --env UV_VENV_SEED="${UV_VENV_SEED:-1}" \
  --env T2_SKIP_SYNC="${T2_SKIP_SYNC:-}" \
  --env T2_PYTEST_ARGS="$PYTEST_ARGS" \
  --volume "$REPO:/work" \
  --workdir /work \
  "$IMAGE" bash -s <<"CONTAINER" 2>&1 | tee "$LOG"
set -uo pipefail
echo "=== stage 0: platform identity ==="
uname -m
PYTHON_BIN="${T2_PYTHON_BIN:-python3}"
$PYTHON_BIN --version
echo "glibc: $(ldd --version | head -1)"
echo "=== stage 1+2: prep image sanity (GL libs + uv are baked in) ==="
if ! command -v uv >/dev/null 2>&1; then
  echo "uv missing on prep image -> building it via scripts/t2/Dockerfile"
  exit 97
fi
uv --version
echo "=== stage 3: frozen wheel availability proof (uv sync --frozen) ==="
if [ "$T2_SKIP_SYNC" != "1" ]; then
  uv sync --frozen
else
  echo "T2_SKIP_SYNC=1 -> reuse mounted project environment"
fi
uv run $PYTHON_BIN - <<'PYPROBE'
import PySide6
import build123d
import cadquery_ocp  # noqa: F401  (import proves the loaded ocp wheel works)
import mycad
print("PySide6", PySide6.__version__)
print("build123d", build123d.__version__)
print("mycad import ok")
PYPROBE
# bind-mounted repo is owned by the host UID; git refuses otherwise
git config --global --add safe.directory /work
echo "=== stage 4: pytest (offscreen; subset via T2_PYTEST_ARGS) ==="
# shellcheck disable=SC2086
uv run pytest $T2_PYTEST_ARGS
rc=$?
echo "=== stage 5: verdict rc=$rc ==="
exit $rc
CONTAINER
rc=$?
echo "T2 script exit code: $rc"
exit $rc
