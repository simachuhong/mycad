# M2-A Implementation Plan

> Execute with superpowers:executing-plans and test-driven-development.

**Goal:** Deliver the approved datum creation, unified scene interaction, positioning and v6 transaction workflow.

**Architecture:** Neutral spatial display and interaction values cross the existing core/geom/UI ports; isolated candidate sessions carry scene data and enforce source/generation validity. The Qt datum task consumes those values and commits only through the original Command Bus.

**Tech Stack:** Python 3.12, PySide6, pyqtgraph, build123d, pytest.

**Spec:** `docs/superpowers/specs/2026-11-03-m2a-datum-interaction-design.md`.

## Global constraints

- Preserve core/geom/UI import boundaries, existing dirty work, replay identity and v6 schema.
- Datum and sketch creation remain separately confirmed; M2-B and later features are out of scope.
- Empty models, failed candidates and stale generations must never select or commit source geometry accidentally.
- Numeric placement is never resnapped; exact anchors are supplied by the geometry adapter.

## Review focus

- Empty mesh with datum outputs must remain displayable and selectable.
- Stale source revision, session, generation and late preview cannot authorize a commit.
- Hidden and overlapping datums must have deterministic, identity-based interaction.
- Rotated workplanes and parent frames must correctly map rays and numeric UV without snapping.
- v4 redo and audit information must remain untouched on cancellation or failure.

## Tasks

1. **Neutral datum display:** Add typed immutable spatial display records to the core viewport port; expose evaluated frames and names from `geom/kernel.py`; extend isolated candidate previews to expose candidate datums even with no mesh. Tests: `tests/geom/test_spatial_datums.py` and `tests/app/test_replay_candidates.py` cover source/candidate separation and empty models.
2. **Shared positioning:** Add a backend-neutral ray/plane and snap service in `core/spatial_positioning.py` with tests for tilted frames, invalid rays, UV roundtrip, exact anchor priority, independent grid and numeric input. Geometry adapter supplies exact BREP and sketch anchors without sampling-based false precision.
3. **Unified scene interaction:** Extend viewport state, rendering and picking to bind the same document/session/candidate/generation, render datum axes/planes without mesh, enforce visibility/filtering, and provide deterministic overlapping selection and invalidation. Test `tests/ui/test_viewport.py`, `tests/ui/test_picking.py` and new targeted interaction cases.
4. **Datum task and origin positioning GUI:** Add focused Qt task controls and connect main window, structure tree and viewport. Support relative coordinate systems, principal/offset planes, staged preview, plane locking, parent-frame conversion, precise point input and explicit confirm/cancel. Tests cover empty part, selection/visibility, source modification and multi-document state.
5. **Persistence and integration:** Verify v4/v5 migration/redo, cancellation, stale grants, error handling, save/reopen/undo/redo and complete parent chain. Update user documentation. Run scoped four gates during development and final integrated four gates once; record real desktop acceptance and remaining limitations honestly.

Each task follows red→green tests and retains the source Bus as the only writer. No commits are created while the user's existing changes are intermingled.

## 2026-11-03 用户补充：待开发与验收

以下两项是用户补充的工作。坐标系直接取点已实现并经定向验证，仍待人工 GUI 验收；球体尚未实现。建议在验收取点后补齐球体，再继续 M2-B。

1. **坐标系原点捕捉实体特征点（待人工 GUI 验收）**：坐标系预览显示原点热点，可点击后点选或拖动到精确 BREP 顶点、开放边弧长中点及圆/圆弧中心，直接采用真实世界 XYZ；保留原先工作平面定位及显式一次投影。定位值转换为父坐标系局部坐标，仅更新草稿，仍需外层确认；过期候选和隐藏对象不可捕捉。自动测试覆盖长方体离面顶点、中点、拖动、过期以及现有定位；尚需人工验证圆柱圆心、不同视角、父系旋转和保存重开。重叠锚点的显式选择与遮挡规则仍需完善，不能宣称支持所有几何特征点。
2. **球体基本元素**：当前 `feature.sphere` 被内核测试明确作为未实现命令拒绝。补齐可重放的球体创建命令、参数校验、几何内核及三维 GUI 入口、预览/确认/取消、定位与必要的实体操作；明确半径、球心、单位及与现有新建/合并/切除模式的兼容规则。验收包括空零件创建、非法半径拒绝、球心与解析体积、预览不改源文档、提交/撤销/重做、保存重开及现有实体操作回归。球面中心捕捉等具体特征点能力另行定义和验证，不能仅凭球体可见就算完成。
