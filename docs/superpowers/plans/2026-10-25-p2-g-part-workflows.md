# P2 G representative GUI workflows

Continue inline under the original P2-32–P2-37 plan. The requirement is complete part workflows, not command-button presence.

- [x] Build a flange from an empty document using sketch tools, concentric rings, draft circular hole pattern and sketch extrusion; verify geometry, live dimension revision, undo/redo, archive and STEP.
- [x] Build a stepped shaft from a closed XZ polyline through sketch revolution; verify axis, volume, repeatable history, archive and STEP.
- [x] Build an arc-ended mounting plate with a slot and hole pattern from lines/arcs/circles, then extrude; verify closed outer/inner loops, holes, undo/redo, archive and STEP.
- [ ] Exercise failure/correction through the same UI and map the shared interaction gates to evidence; keep display/native-user checks distinct from automated Qt event paths.
- [ ] Repair actual gaps with regression tests, scoped verification and evidence. Preserve original task scope, shared worktree and existing audit history.

All creation steps use GUI controls or Qt mouse events. Read-only geometry assertions and file round-trip checks may use application/STEP helpers; no direct Bus execution may create a representative part.

## 孔阵列中心补充

发现 GUI 始终将所点位置覆写为阵列中心，环形面圆心落在孔洞中无法点选。复用已支持的 position.kind=center 面形心语义，增加“点击位置/面形心”选项，默认保留原点击行为。先选面再切中心方式应立即更新预览和定位文字；不新增命令语义，不猜测拓扑的几何圆心。验证环面阵列与点击模式、过大孔纠错、参数修改及草图尺寸驱动后重开。
