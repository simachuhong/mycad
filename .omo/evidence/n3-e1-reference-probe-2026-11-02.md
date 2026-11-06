# N3 E1 面引用与孔位置实验

日期：2026-11-02。基线 `ba2f539` 加既有未提交 N1/N2/N6 原型。新增内容仅为 `tests/geom/design_reference_probe.py`、`tests/geom/test_design_reference_probe.py`、计划和证据；本轮未修改生产代码、命令或文件格式。

## 观察

- box/cylinder 经两次真实 Boolean cut，按当前输入形状的原生 IsSame 找来源，再消费该次结果映射；保留顶面方向，面积和体积满足解析值。独立审阅用探针确认 box 的顶面索引从 5 变为首刀结果的 2，测试不是依赖索引恰好不变。
- 独立创建的同形面不能作为来源；真实 split、merged、deleted 拒绝继续，并保持原输入体积/面积。缺失 history 用受控故障注入验证安全失败，不用几何相似度补猜。
- 20×20×4 盒体切除右侧 x=7…10 条带，顶面质心由 x=0 变为 x=-1.5。以来源平面局部点 (-4,3) 放置孔时，实际孔壁中心保持 (-4,3)，直径 2；剩余体积为 1360−4π mm³。
- 盒体高度由 4 改为 8 后重新构造来源与坐标系，实际通孔仍在 x=-4,y=3，深度跟随厚度；旧高度的世界平面不能悄悄投影到新面。
- 左、右圆柱位于 x=-20/+20，右半径 8，左半径分别 10、5、8：已知左来源的面始终留在左侧，真实孔壁中心、深度、半径及总体积正确。此为 E07 类几何实验，不是历史命令身份测试。
- 局部盲孔的实际孔壁中心、直径、上下界、面积和去除体积均按独立解析值检查；非有限坐标、面外点、已有孔洞区域和反向平面被拒绝。

## 验证与诊断

初始 stub 的首个测试因 NotImplementedError 失败，确认原型尚无行为。实现后首轮 12 passed / 1 failed：测试错误地使用圆柱面的默认 center() 测孔轴；锁定 build123d 源码表明，曲面的默认中心是 UV 中点，平面默认中心则是面积质心。将孔壁测量明确改为 CenterOf.MASS，未改产品行为。

严格类型检查发现 build123d 的泛型 is_same 和 from_local_coords 暴露 Unknown；采用已有项目风格的局部 Protocol 和显式 Plane 基向量变换，无类型抑制。后续 ruff SIM300 自动整理断言两侧，不改变断言内容。

- `uv run pytest tests/geom/test_design_reference_probe.py tests/geom/test_topology_evolution.py tests/test_layering.py -q`：30 passed（当时 E1 为 19 项）。
- 加入盲孔及补强重建后的孔壁断言后，`uv run pytest tests/geom/test_design_reference_probe.py -q`：最终 20 passed，8.21s。
- 新增两个 Python 文件执行 scoped ruff、format 和 basedpyright；最终均通过，basedpyright 为 0 errors、0 warnings、0 notes。
- 独立审阅指出尺寸变化测试应检查实际孔壁，已补充；其余未发现可操作的正确性问题。未运行全仓四门或远端 CI，不重复验证已确认的全仓工作。

## E2 建议与限制

支持进入 E2 的格式比较及事务设计：操作历史确实能在这些有限案例中支撑多步面追踪；定位必须单独表达面心与局部坐标意图。先比较新格式命令实例字段与顶层实例表，验证默认命令派发、redo、旧档及嵌套来源，不凭 E1 决定 v5。

原型由调用方提供已知来源形状及局部 Plane，并在重建时显式重新选择 primitive 角色；没有持久命令 UUID、自动来源坐标系、Bus 重放、完整特征 lineage、GUI 拾取/修复或存档。局部孔 cutter 由实验代码显式构造，证明几何意图可检验，不代表生产 hole 命令已实现局部坐标。这里的保守 split/merge 拒绝只是一项边界，不能等同于 Solid Edge 的行为。N3、P2-12/19 保持未完成。
