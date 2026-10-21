# 手工 QA 清单 — 阶段 1 桌面壳交付前（勾选项必须附实测输出）

## A. 可本会话已实测（自动通过，勿重勾）

- [x] CLI 四门: mycad commands/plugins/validate/run --json（后续 todo 实测通过）
- [x] offscreen headless GUI 全量: 882 passed 含 tests/ui/*（81 文件）
- [x] 存档往返: flange .mc.json 保存/重载/重放（后置 todo 实测通过）
- [x] 计划六态机: draft→confirm→execute→done 全链（后置 todo 实测通过）

## B. 需桌面会话（用户可执行，各附验证要点）

- [ ] `uv run mycad gui` 于真实 X11/Wayland 会话启动，源窗标题含工作目录
- [ ] 五区布局: 左命令库/中 GL 视口/右 Tabs/底栏 CLI+Chat 比例与 resize 行为
- [ ] GL 视口: flange φ80 渲染、鼠标旋转缩放、射线拾取高亮 overlay
- [ ] 生命周期: 新建→执行命令→undo/redo 全量重放视觉一致→保存 .mc.json
- [ ] 保存确认对话框出现（offscreen teardown 曾挂此路径，需实机验证修复）
- [ ] 工具栏按钮触发命令（无 action 需绑定提示，初稿实现差异项）
- [ ] CLI Tab 命令执行与底栏命令历史联动
- [ ] QSettings 记忆: 重启后菜单/工具栏位置、窗口尺寸恢复

## C. 需 T2 aarch64 实机（风控清单引用）

- [ ] glibc≥2.39 信创发行版（如麒麟 V11 aarch64）`uv sync` + `mycad gui`+
      880 测试复跑（QEMU deselect 两项在本机应 PASS）
- [ ] NF-04 open 回放性能门 <1000ms 原生机复核
- [ ] GL 视口原生 GL 渲染（qemu-user 下 GL 上下文不可考，非回归）

## D. CI（todo 13 收口，等 draft PR）

- [ ] https://github.com/simachuhong/mycad/compare/main...phase1-desktop-shell
      开 draft PR → ubuntu-22.04 / ubuntu-24.04 / windows-latest 三 job 全绿
