# P2-06 — 按命令 ID 和版本绑定验证、执行与重放

日期：2026-10-24；分支 `codex/phase2-foundation`；本批为工作区改动。

## 改动与行为

- 新建交互命令在未指定版本时继续选择注册表最新版本；API 可显式指定版本。Registry 提供版本枚举与全部 spec 查询。
- 计划文件按 step 的 `id` 与 `version` 选择精确参数 schema；缺少 version 或引用未注册版本会给出明确错误。批执行将该版本传给 Bus。
- Bus 将 spec、handler、执行上下文和历史记录按 `(command_id, version)` 绑定。历史编辑校验记录版本；undo、redo、编辑恢复和打开存档的重放均使用历史中的版本。
- 插件 handler map 改为 `(id, version)` 键，同一 ID 的不同版本各自调用工厂并保留独立 handler。旧式 ID-only handler 映射仅在该 ID 只有一个注册版本时兼容；多版本时不会回退到此 handler。
- pre/post command 与 command amended 信号现在包含 `command_version`。`.mc.json` archive format/version 保持 v1，命令审计六字段和命令版本字段未变。
- CLI alias 解析只读取每个命令 ID 的最新 spec，避免旧版本独有 alias 用旧 schema 解析后又按 latest handler 执行。
- 更新 ADR-003 与 README 的版本策略说明。

## 验证

- scoped pytest：Bus、Document/DTO、Persistence、Handler/Kernel Protocol、历史隔离、Core integration、插件 loader、命令注册/grammar、JSON 计划、App composition/open atomicity 和 UI 菜单工具栏路径：**252 passed**。
- 对改动的 src 与测试路径执行 `uv run basedpyright ...`：0 errors / 0 warnings / 0 notes。
- 对改动路径执行 Ruff check 与 format：通过。
- `git diff --check`：通过。
- E06 回归覆盖：v1/v2 schema 不兼容时显式 v1 计划和历史按 v1 校验；同一存档并存 v1/v2 命令时分别执行对应 handler；打开重放、历史编辑和批执行都核对版本；缺失/未注册版本有明确错误；多版本命令的 ID-only handler 不会跨版本复用。
- 代码审查发现旧版本独有 CLI alias 仍会解析到旧 spec；新增 alias 回归测试先复现，再改为只解析 latest spec 后通过。复审确认问题关闭，没有新的发现。

## 限制

本轮只运行受影响路径的定向测试，未运行完整 pytest 全量门，也未做 Windows/CI 交叉平台验证。
