# P2 G 最终审查修复证据

2026-10-25。对应 `task-P2-G-final-review.md` 的五项 Important，父代理全部复现并修复。只进行一次 reviewer；修复后未再发起审查。最终全量门及两项集成失败修复已记录在 `task-P2-G-final-integration.md`；人工验收未执行。

## 1. 闭合路径顺序

`core/sketch_edit.py::_closed_path_points` 收集顶点的展开周长位置，按位置排序再输出，跨起点不再按旧下标输出。矩形/闭合折线、trim/split、点击短区间/跨起点长区间共8种，断言精确路径、保留长度、稳定身份、图层和剪切器不变。

Red：6 failed / 2 passed。修复后该模块 **66 passed**，exit0。

## 2. DXF bulge 与宽度

用 `xyseb` 读取完整顶点数据。在转换前识别非零 bulge、分段起终宽度和 const_width，明确跳过原实体并将理由加入报告，report.complete=false；正常其他实体继续导入。没有引入不精确的折线近似或改变原有直段子集。

Red：正/负bulge × 开/闭、恒定/分段宽度共 **6 failed**。修复后 DXF exchange **21 passed**，exit0。带 bulge 的 LWPOLYLINE 尚不支持；独立 ARC 解析和既有闭合直线折线仍支持。

## 3. 图层锁定与求解

直接 driving add/update/drag 引用锁定图元时返回 invalid 并说明解锁/参考尺寸选项。所有锁定图元坐标/半径/角度以 PlaneGCS fixed parameters 创建，故已有关系也不能间接移动它们；返回时保留原数据精确值。未锁定相邻几何仍可在锁定锚点约束下求解。锁定实体在对话框明确标注，参考测量仍可预览确认，解除锁定后能恢复修改。覆盖线/折线/矩形/圆/顺逆圆弧。

Red：直接锁定圆驱动修改与间接关联移动 **2 failed / 1 passed**；UI 标识另 **1 failed**。修复后完整 geometry constraints + dialog **74 passed in 25.45s**，exit0。无 schema/旧冻结解改写。

## 4. 精确轮廓判定

复用 build123d/OCCT 原生 Face validity、wire distance/closest points、Face containment、face normal 确认轮廓/接触/包含/方向。采样保留用于错误区段诊断，不决定几何接受或拒绝。跨轮廓错误报告精确接触位置和双方身份。

新增近内切有效圆/双圆弧、嵌套实体岛、XY/XZ/YZ、真实内切/交叉/外切。Red **7 failed / 2 passed**（不仅误拒有效间隙，还发现原近似漏掉真实外切）。实现时首轮将 tuple 传给 Vector.dot，17项失败；依据已安装API改为 Vector 后完整 extrusion **29 passed**，exit0。没有以加密固定采样掩盖根因。

## 5. 文档修订与确认

普通建模和圆角预览记录 Document.revision；回调和提交均检查当前修订。写入/撤销/重做/改参事件使预览和待处理状态立即失效，自身已授权的提交保留完成回调；输入/选择仍可修正并重新预览。修订号能识别 undo→redo 后历史内容相同但已经变更的情况。

Red：undo、redo、外部write、amend、undo→redo、事件投递前立即确认共 **6 failed**。Green **6 passed in 19.18s**。另增加圆角确认前同历史不同revision的回归；显式重新输入后正常预览和提交得到保留。

## 修复轮统一增量结果

```text
QT_QPA_PLATFORM=offscreen uv run pytest \
  tests/core/test_sketch_edit.py tests/formats/test_dxf_sketch_exchange.py \
  tests/geom/test_sketch_constraints.py tests/geom/test_sketch_extrusion.py \
  tests/ui/test_sketch_constraint_dialog.py tests/ui/test_modeling_interaction.py \
  tests/ui/test_fillet_interaction.py tests/test_layering.py -q
240 passed in 94.77s (0:01:34), exit 0
```

13个变更 Python 文件 Ruff 通过、format 通过。类型检查发现第三方泛型Shape方法部分unknown、可空message、测试tuple宽度三个问题，使用窄Protocol、显式None检查和三元坐标修复，无ignore。前12文件修复后仅剩fillet测试tuple问题；单文件复查 **0 errors / 0 warnings / 0 notes**。最终全树门另行记录，避免用增量结果冒充全量。

日志在本机 `/tmp/mycad-review-*.log`；本文件记录关键命令、实际失败与结果，不依赖临时日志作为唯一证据。
