# P2-34 偏移异常与引用保护定向检查

2026-10-25。复现了开放多段线偏移缺少守卫：U 形开路径内偏移 6 mm 后中段方向反转；交叉开放路径偏移 0.5 mm 后仍自交。原实现直接返回结果，两个新测试均因未抛错失败。短边和反向折返无唯一交点的两个案例已由原实现正确拒绝。

修复共用原有线段相交判断，提取 `polyline_self_intersection` 供闭合轮廓及偏移结果使用；开放/闭合偏移均检查结果边方向，对交叉/相触/交叠报告图元 ID 与段号。保留原闭合轮廓面积及有效性验证，不改变一般开放多段线绘制语义。另补非相邻线段交叠测试。

GUI 检查：偏移失败保留原图元/约束/选择；改有效距离后成功产生新身份副本，undo/redo 恢复相同身份。用户尺寸引用的草稿直线不能通过分割或普通移动静默改写/转接，错误明确且不产生草稿历史。

最终范围：`QT_QPA_PLATFORM=offscreen uv run pytest tests/core/test_sketch.py tests/core/test_sketch_edit.py tests/ui/test_sketch_editor.py tests/test_layering.py -q` → **136 passed in 27.17s，exit 0**。四个变更文件 Ruff check、format --check、basedpyright（0 errors/0 warnings/0 notes）通过。

一次组合回归暴露既有附着草图测试竞态：只等内核已有草图，Bus 还未追加命令就断言历史。改为等真实命令已提交且执行单元空闲，再检查历史/身份；未改产品执行顺序。初次 135 passed / 1 failed，最终 136 全绿，失败运行不算通过。

本项为原 P2-34 定向证据；整体 P2 G 仍待共同门槛与最终审查，用户人工验收未执行。
