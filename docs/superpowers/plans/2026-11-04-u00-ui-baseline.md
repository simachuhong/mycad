# U00 UI 参考与现状基线 Implementation Plan

> **For agentic workers:** 使用 superpowers:executing-plans 逐项执行；本包是证据登记，不修改产品行为。

**Goal:** 为首页、零件、零件草图、工程图和独立二维建立分开的参考、现状、动作及验收账本。

**Architecture:** 沿用已有 ST10 验收文档，新增 AutoCAD 独立基线和 U00 证据索引；源码观察、历史证据、官方资料与实机验收分别标记。

**Tech Stack:** Markdown、PySide6 源码与既有 pytest UI 测试。

**Spec:** `docs/design/2026-11-04-unified-ui-design.md`；`docs/design/2026-11-04-unified-ui-todo.md` 的 U00。

## Global Constraints

- ST10 有序与同步分开；2019 截图仅作视觉参考。
- AutoCAD 锁定产品、年份及工作区，未知实机设置标待核对。
- 缺失画面和行为不得标为通过；自动测试、参考核对和用户验收分开。
- 保留现有未提交改动，不更改应用、依赖或测试逻辑。

## Review Focus

- 无参考实机：记录缺失，不推断版本专有行为。
- 旧探针来自旧源文件：记录来源哈希，不当作当前结果。
- 同名入口不同语义：标注动作身份和触发路径。
- 二维和工程图均有“图”称呼：分开文档与验证。
- 现有测试存在不代表本轮通过：注明仅为候选验证命令。

## Tasks

- [x] 建立七组画面和模式、语言、缩放及来源登记；缺失项明确待采集。
- [x] 记录源码可核实的动作、入口、条件、处理路径、重复项及占位，提供后续逐项扩充边界。
- [x] 建立 HOME、COMMON、ST10-UI、ST10-S、ACAD-2D、DRAFT 自动与人工取证映射。
- [x] 核对文件链接、目标覆盖及状态，不以文档登记代替参考核对。
- [ ] 采集七组真实画面并核对 ST10 有序/同步及 AutoCAD 锁定配置；在参考实机可用时进行。
