# Todo 20 — GUI 命令速查对话框（动词 ⇄ 命令 ID 对照表）

**动机**：人工 QA 中用户在 CLI 里敲 `feature.box` 被拒（`unknown command verb 'feature.box'`）。
根因非缺陷：CLI 动词是短名（box/cylinder/extrude/revolve/hole/hole-pattern/fillet/cut），
命令 ID 才是 `feature.*` / `modify.*`；新用户最易混用二者，而 GUI 内此前无处可查。

## 改动

1. `src/mycad/commands/grammar.py`：新增 public `ParamDoc(key, required, children)` 与
   `describe_params(spec, defs) -> tuple[ParamDoc, ...]`——展开 `#/$defs/<Name>` 引用（复用既有
   `_deref`/`_as_mapping`/`cast`），顶层键 + 必填标记 + 一层子键名；oneOf 变体（FaceSelector/Depth/
   Pattern/Profile/Tool）取分支并集。`__all__` 增补 `ParamDoc`/`describe_params`。
2. `src/mycad/ui/command_reference.py`（新文件）：`CommandRow`(verb/command_id/label_zh/summary_en/params)
   + `collect_rows(registry)`（按 verb 排序，参数渲染 `key*`=必填、`key(sub1, sub2)`=嵌套子键）
   + `CommandReferenceDialog(QDialog)`（搜索框 + 5 列表格：动词 / 命令 ID / 名称 / 说明 / 参数 + 底部提示 + 关闭按钮）。
3. `src/mycad/ui/main_window.py`：帮助菜单新增「命令速查…」动作（默认禁用，仅 services 分支启用），
   `_show_command_reference()` 打开对话框；无 services 时不弹（与既有降级语义一致）。
4. `tests/ui/test_command_reference.py`（新文件，4 例）：
   - `collect_rows` 暴露 verb/ID/参数（cylinder→feature.cylinder；hole-pattern→feature.hole_pattern；
     cut→modify.boolean_cut；参数含 `radius*`/`target_face*`/`surface`）；
   - 对话框行数与过滤（"hole"→2 行；"cylinder"→1 行且列 0/列 1 分别为 `cylinder`/`feature.cylinder`）；
   - 帮助菜单动作可触发并打开对话框（monkeypatch 对话框类为 stub）；
   - 无 services 时该动作禁用。
5. 文档：`docs/UI设计初稿.md` §3 帮助菜单行增列「命令速查（动词⇄命令 ID 对照表）」；
   §实现注记新增「命令速查」条目（只读呈现，不提供执行入口）。SHA256 基线按流程重生成
   （`scripts/gen_baseline_hashes.py`）。

## 本机渲染实证

- 对话框在真实 X11 显示上渲染成功（`/tmp/opencode/show_ref.py` → `/tmp/opencode/ref_dialog.png`）：
  8 行 × 5 列，首行 `box | feature.box | 长方体 | Create a rectangular box | size_x*, size_y*, size_z*, center, mode`；
  底部提示常驻（CLI 只认动词 / 嵌套参数点号展开 / 完整示例指向 examples/flange_script.txt）。
- 首版列宽把「命令 ID」「说明」挤成省略号（`feature.boo…`）→ 改为显式列宽策略
  （动词/命令 ID/名称 = ResizeToContents，说明 = 固定 240，参数 = Stretch），复渲染确认可读。

## 顺带发现：QSettings 布局 blob 会带回"工具栏停靠到底部 + 左面板隐藏"

重启 live 实例做渲染实证时，截图显示工具栏停靠到了窗口**底部**、左「命令库」dock 整个消失
（视口占满左侧）——根因是 `~/.config/MyCAD/MyCAD.conf` 里的 `saveState` blob 记录了
"工具栏在下 + 左 dock 隐藏"的旧布局。清空 conf 重启后默认布局回归正确：
菜单栏 → **工具栏 12 按钮（菜单栏正下方）** → 左命令库（搜索框 + feature/modify 树）→
中 GL 视口 → 右属性（四 Tab）→ 底控制台（CLI/Chat）→ 状态栏「空闲 / 就绪 / 未修改」。
结论：布局由 QSettings 记忆（视图菜单可切回），陈旧 blob 需手动清一次；
restore 语义未改（QSettings 往返有测试钉住）。

## 门禁（实测）

- `ruff check .` All checks passed；`ruff format --check .` 188 files already formatted
- `uv run basedpyright` 0 errors / 0 warnings / 0 notes
- `uv run pytest -q` 892 passed（基线 888 + 本轮 4）

## 已知边界

- 对照表是**只读**的：执行路径不变（命令库双击起草 → Chat 计划卡片确认 → 执行），避免把
  速查表变成绕过确认红线的执行入口。
- 参数列只展开一层嵌套键名（再深的层级折叠为括号内并列子键），避免表格过宽。
