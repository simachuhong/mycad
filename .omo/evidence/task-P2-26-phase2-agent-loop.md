# P2-26 — Current revision, desktop, and downstream delivery evidence

Date: 2026-10-24

## Revision and environment

- Branch: `codex/phase2-foundation`.
- HEAD: `9ab55ac267ffb6ef19fa45321b027048ef7782b2`.
- The requested Phase 2 changes, including E, remain uncommitted in a shared working tree with other P2 work. HEAD is the baseline commit, not the submitted working tree.
- Environment: Ubuntu 24.04 x86-64, Python 3.12.3, glibc 2.39, X11 `DISPLAY=:1`; no Wayland session.

## Verified locally

- A fresh headless install and flange CLI run passed; see [P2-25 evidence](task-P2-25-phase2-agent-loop.md).
- `mycad gui` started under the current X11 session and remained in its event loop until the 30-second smoke timeout. The captured MyCAD window is [p2-26-x11-startup.png](phase2-foundation/p2-26-x11-startup.png). The smoke used a new empty document; it does not prove model rendering, camera controls, picking, save dialogs, or layout persistence.
- GitHub Actions lookup for HEAD returned no workflow runs and no combined status checks. No remote run can describe the uncommitted working tree.

## Not verified; task remains partial

- The current modified tree has no exact-commit T1 CI result. Windows and Wayland desktop runs were not available.
- Full real-desktop checks for model rendering, camera, picking, save dialogs, layout memory, and long-task interaction were not performed.
- `FreeCADCmd`, `freecadcmd`, and `freecad` are not installed here, so no downstream STEP-open inspection was available.
- Install/upgrade/rollback behavior and release packaging were not assessed. The phase gates A/B/U/C are not all complete; P2-12 and P2-19 remain partial.

No commit, push, PR, or release was created.
