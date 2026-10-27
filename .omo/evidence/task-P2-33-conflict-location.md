# P2-33 冲突对象定位与纠错

2026-10-25，补齐原范围“冲突指出相关对象/约束并可恢复”。

求解器已有稳定冲突/冗余 ID，但原界面只列英文类型和短 ID；失败时没有对应图元显示。新测试分别证明缺少中文具体引用，以及真实水平/竖直冲突没有任何定位预览。

现在详情把已有与当前候选约束映射为中文关系、草图元素编号/类型/短 ID、起点/终点/整图元/子段引用。失败有诊断时仅返回并标红原模型对应图元，不展示或安装部分求解几何；成功分支警告仍橙色。改变输入、取消或过时回调沿用现有失效门禁。确认只在真实成功预览后启用。

真实 GUI 场景：已有水平线添加竖直关系，确认禁用、原草图/历史不变、原线标红；改为长度 20 mm，恢复正常颜色和有效预览，再确认成功。最终范围 `tests/ui/test_sketch_constraint_dialog.py tests/geom/test_sketch_constraints.py tests/core/test_sketch_constraints.py tests/test_layering.py` → **87 passed in 23.58s，exit 0**。三个变更 Python 文件 Ruff/format/basedpyright（0 errors/0 warnings/0 notes）通过。

初次真实测试使用了存档创建契约不允许的“用户水平关系”初始夹具，先改为已允许且几何满足的推断水平关系，再复现缺失高亮的红测试；未绕过或改变草图创建校验。最终真实求解与失败→纠错提交均通过。

XCB 隔离 QSettings 截图程序退出 0；已检查 `phase2-g-constraint-conflict/conflict-dialog.png`、`conflict-geometry.png`：中文关系和图元引用、禁用确认、原线标红而无关圆未标红。不是用户人工验收。

剩余为全条款与共同交互门槛审查、最终一次独立审查及全量质量门。目标保持 active。
