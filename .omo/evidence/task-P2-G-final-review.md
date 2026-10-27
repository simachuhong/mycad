# P2 G 最终独立审查

2026-10-25，reviewer `/root/p2g_final_review`，全新上下文 Astra，实际共享 working tree 只读检查（HEAD 9ab55ac）。范围 P2-32～P2-37，风险导向检查并运行最小复现；没有逐行审查全部 P2 改动、外部 CAD 或平台验收。无源码/Git 修改，无残留诊断进程。reviewer DoneClaim 已收到；不能以 DoneClaim 代替修复验证。

## 报告与父代理裁决

五项 Important，全部接受，均属于原范围的实际正确性问题；无 Critical 或 Minor：

1. `core/sketch_edit.py::_closed_path_points` 跨闭合路径起点时顶点顺序错误，修剪/分割生成逆序/对角线。20×20 方形、底边 x=5/15 两切线可复现。
2. `formats/providers/dxf_provider.py::_read_entity` 只取 xy，bulge=1 半圆静默变成直段且 report.complete=True。需显式支持或拒绝报告，同时检查宽度。
3. `geom/sketch_constraints.py` 未保护 locked 图层；半径5锁定圆可以驱动改成7。覆盖 add/update/drag 及间接移动；参考测量可保留。
4. `geom/sketch_profiles.py` 用固定采样多边形判断相交/包含，误拒绝真实有效内外圆。外R100/内R10，内圆心距离89.99、角360/256度，精确间隙0.01；原生 Face 有效且面积9900π。
5. `ui/main_window.py` 成功预览未绑定当前文档历史；已有box→预览第二box→undo第一box→旧确认仍有效，实际提交与预览不同。需修改事件失效和提交时再次验证两层保护。

审查肯定已有冻结解重放/审计、孤立候选重建、版本保护、显式确认、体来源以及 DXF 精确字节预览原子写入，但这些不抵消上述缺陷。结论：with fixes，尚不可声明 P2 G 完成。

## Declined-to-judge 的逐项裁决

- 完整 Solid Edge 同步/IntelliSketch、装配及装配持久身份、商业格式：原范围之外；保留边界。
- 已提交草图自由画布几何编辑：用户明确仅未提交草稿；已有数值尺寸修改仍在范围内。
- 复杂偏移拓扑自动修复/其他接角样式：明确拒绝可接受；静默损坏不接受。
- 整圆或折线内部段延伸：无合适开放端点，显式不支持；不伪称全部延伸能力。
- DXF 全实体/字体/布局、无MyCAD关联的外部尺寸：子集允许报告跳过；第2项静默丢失必须修复。
- Windows/aarch64 solver、目标 AutoCAD/Solid Edge 渲染、真实输入设备体验/性能：Linux审查不构成这些验收；保留平台/人工待验。
- 数学解唯一性：未承诺；保守分支反馈不等于唯一性证明。
- 负360°阵列疑点：已由公开schema拒绝，非问题、非延期项。

不派发第二 reviewer。父代理执行一次必要修复轮，再运行最终全量门。修复结果另记 `task-P2-G-final-review-fixes.md`。
