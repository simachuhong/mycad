# Todo 15 process evidence: T2 aarch64 QEMU regression

Deliverables: `scripts/t2_qemu_regression.sh` (rerunnable, exit 0), `scripts/t2/Dockerfile`
(prep image: ubuntu:24.04 + GL/xkb/freetype/fontconfig/dbus/mesa-dri/venv/git + uv),
conclusions in `t2-qemu-regression-phase1-desktop-shell.md` (same dir).

Script iterations (all under emu): docstring->comments fix, set -u defaults, docker -i
for heredoc stdin, PY detection, package-name fixes (libxkbcommon0), prep-image baking,
host-mounted UV_PROJECT_ENVIRONMENT/UV_CACHE_DIR for rerun reuse,
git safe.directory for the bind mount, python3.12-venv for ensurepip,
UV_VENV_SEED, LIBGL_ALWAYS_SOFTWARE probe (documented, insufficient for GL).

Big-to-small progression: bookworm probe exposed the glibc 2.39 wheel gate (finding 1)
before the ubuntu:24.04 route went green. Full-suite runs: 3f/304p (partial lanes) ->
306p/1 deselected (non-Qt scoped) -> 68p/1f UI -> 880p/2 deselected / exit 0 (final).

DISCOVERY: aarch64 closure gains py-lib3mf -> NOTICE attribution added (finding 4).

CI matrix untouched; no tests deleted; no hardware purchased.
