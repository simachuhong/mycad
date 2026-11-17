# Draftwright 工程图参考

2026-11-07，根据用户指示，将 Draftwright 作为工程图开发的技术参考。用户提供的 ST10 Draft 录像仍是交互参考；两者解决的问题不同。

## 可参考的架构

[Draftwright 项目](https://github.com/pzfreo/draftwright)将来源几何的特征识别、制图意图、视图投影、页面布局、标注与输出分开，并列出剖视、剖切线和剖面线能力。MyCAD 可以借鉴这些职责边界：可重放的工程图对象进入 Command Bus，几何操作留在 `geom`，UI 只管理命令草稿和交互。不能把自动特征识别的结果直接当成用户确认的制造意图。

## 许可和依赖

- Draftwright 主项目的 [许可证](https://github.com/pzfreo/draftwright/blob/main/LICENSE)是 AGPL-3.0；MyCAD 为 Apache-2.0。本轮仅参考公开架构，不直接复制主项目源码或引入该运行时依赖。
- [build123d-drafting-helpers](https://github.com/pzfreo/build123d-drafting-helpers) 和 [quiddity](https://github.com/pzfreo/quiddity) 是分别发布的 Apache-2.0 组件，可按具体需求单独评估；其许可证、通知、锁定版本、平台闭包及 API 兼容性须在实际采用时核实，本轮尚未引入。
- 截至本次核查，Draftwright 的 [依赖声明](https://github.com/pzfreo/draftwright/blob/main/pyproject.toml)对 Python 3.12 约束 `build123d<0.11`，对 Python 3.13+ 又排除 `cadquery-ocp-novtk==7.9.3.1.1`；均需与 MyCAD 固定的 `build123d==0.11.1` 和 OCP 范围逐平台核对，不能直接假设可共存。

## 剖视实现关注点

ST10 01 号录像 07:40–08:30 显示选取来源视图、绘制剖切线、放置剖视和剖面线。MyCAD 的首个剖视切片需要明确保存剖切平面和观察方向，重算来源变化；生成真实剖切投影与材质截面的填充，包含孔洞与多实体；剖切线、视图和标注须保持可识别关联，并能安全处理失效。旧投影缓存、失败回滚、保存重放及 PDF/DXF 输出沿用现有边界。不能只显示平面轮廓或将普通投影标成剖视。

## Ortho2CAD 补充参考

[Ortho2CAD](https://github.com/AdityaJoglekar/Ortho2CAD) 公开的生成器将 STEP 转为第一角正投影，区分可见线和虚线隐藏线，标注模型外包框尺寸；[生成器说明](https://github.com/AdityaJoglekar/Ortho2CAD/tree/main/orthographic_drawing_generation)列出 STEP → SVG → PNG 的批处理流程。项目当前 README 称基于多种数据集生成超过百万张图；数据集规模不表示每张图都经过工程人工验收。外包框尺寸也不等同于特征尺寸或可重附着的关联尺寸。

其 [生成脚本](https://github.com/AdityaJoglekar/Ortho2CAD/blob/main/orthographic_drawing_generation/pythonocc_for_step_to_ortho.py)使用 pythonOCC 的 OCCT HLR；MyCAD 已通过 OCP 使用同一类 HLR，并保留解析曲线和关联引用，而不是仅输出采样图片。可参考其整体投影方向、页面布局与大规模形状样本思路；模型数据的具体来源、数据许可、单位和可用性须逐数据集确认。本次查看的仓库首页和生成脚本没有找到明确许可证，不能据此假设脚本可复制或分发；未引入代码或数据。下一步优先对照第一角视图布局、隐藏线及边界尺寸的行为，避免把包围盒误当作制造特征尺寸。
