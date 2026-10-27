# Phase 2 前期开发首批验证报告

日期：2026-10-23。分支：`codex/phase2-foundation`。
基线提交：`9ab55ac267ffb6ef19fa45321b027048ef7782b2`；以下验证针对当前未提交工作区，不是远端 CI 结论。

## 交付

- 规划完成：Phase 2 基础 CAD、Phase 3 AI/企业/高级扩展分开；数据库默认 MySQL、达梦，列为真实适配与验收任务。
- P2-00：范围基线、需求追踪、阶段约束和首批自主开发边界已记录。
- P2-02：历史参数和审计的深层可变别名已隔离；Bus 改参、撤销重做和存档往返继续可用。
- P2-04：完全切除保留空快照，场景/高亮/选择清空；重绑空文档不残留上一模型。
- P2-28：背景由错误的近透明黑色改为不透明浅灰蓝；整体可视性未收口，任务保持未勾选。
- 附带修复：GUI 测试显式使用临时 INI 配置，避免 NativeFormat 写入用户布局或 Windows 注册表。

## 验证结果

| 检查 | 结果 |
| --- | --- |
| 有效历史隔离反例（修复前） | 4 failed、1 passed；失败分别证明构造/公开历史/改参/handler 别名 |
| 背景、空结果、重绑反例（修复前） | 均失败，错误颜色、旧快照和残留高亮可复现 |
| 相关核心/存档/几何/视口/拾取/分层回归 | 106 passed，42.60 秒 |
| `uv run ruff check .` | 通过 |
| `uv run ruff format --check .` | 194 files already formatted |
| `uv run basedpyright` | 0 errors / 0 warnings / 0 notes |
| `uv run pytest -q --junitxml=/tmp/mycad-phase2-foundation-junit.xml` | **902 passed，137.03 秒** |
| `git diff --check` | 通过 |
| 原 ADR/规格基线/视觉资产/依赖/治理文件摘要 | 27 个文件未变化 |

先按路径验证，最终集成四门仅运行一次；未重复跑已通过的整套测试。JUnit 摘要另保存在本目录 JSON，
临时 XML 不是唯一证据。新增共 10 个测试用例（含参数化实例），不以数量替代下面的真实渲染检查。

## 真实桌面

Qt 平台 xcb（X11），Intel HD Graphics 620，Mesa 25.2.8，OpenGL 4.6 Compatibility Profile。
空文档、法兰、薄板、圆柱实际 framebuffer 背景均为 `(239,243,247,255)`；
完全切除后场景项为 0，质量查询 solid_count=0，画面中心与背景一致。
使用独立进程和临时设置目录；最终探针确认设置隔离，结束后正常关闭窗口并清理临时配置。

- [完整工作台](light-workspace.png)
- [法兰](flange-viewport.png)、[选中法兰](flange-selected.png)
- [薄板](thin-plate-viewport.png)、[圆柱](cylinder-viewport.png)
- [空文档](empty-viewport.png)、[完全切除](complete-cut-empty.png)
- [环境及像素记录](render-check.json)

人工查看上述画面发现模型背光面偏暗、三角边杂乱、高亮不足和部分比例取景不足。
这些是 P2-29/30/31 后续工作的实际输入；本批没有交付原设计稿的完整 UI，也没有修复非空模型历史拾取 P2-05。
没有新 solver/schema/网络/数据库依赖；未运行 Windows/Wayland 或远端 CI，不宣称其已验收。

## 测试隔离故障记录

旧测试夹具仅设置 INI 路径，但 Qt 显式组织/应用名构造实际使用 NativeFormat。
首轮 scoped 测试和首个桌面探针可能读写 `/home/sima/.config/MyCAD/MyCAD.conf` 的窗口布局；
发现后改为测试侧显式 INI factory，并增加真实构造路径断言，Windows 也避免使用注册表。
此前没有配置快照，未猜测或强行恢复用户布局；此影响限于布局记忆，不涉及 CAD 模型文件。
根因、修复和清理回执已追加 ledger。

## 下一批明确边界

优先 P2-01 失败打开原子性、P2-03 失败恢复、P2-06 版本绑定，然后衔接 P2-20 确认一致性。
求解器、存档升级与整体渲染/交互改造按各自设计门推进。当前未创建自动化、未后台定时运行、未提交或推送 Git。
