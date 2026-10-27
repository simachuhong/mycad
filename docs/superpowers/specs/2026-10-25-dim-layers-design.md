# DIM 默认标注层与图纸图层状态

用户确认：新尺寸默认归入自动创建的 DIM 层；可改选标注层。尺寸线、箭头、文字使用同一层的颜色、线型与线宽。显示/隐藏、冻结/解冻、锁定/解锁独立保存；解冻不会打开被关闭的层。冻结不参与显示再生、范围适配、捕捉或选择；当前绘图层不能冻结。图层控制统一作用于草稿和已提交图形，隐藏几何不隐藏独立 DIM 标注。隐藏/冻结不解除驱动约束。支持保存、撤销、DXF 往返及旧标注批量迁移。

采用图纸级图层状态，保留既有中性 SketchLayerTable/SketchConstraint。新增可重放 drawing.layers.set 命令；kernel 的图纸图层状态统一覆盖已提交草图，同步到草稿视图，真相仍由历史重放得到。尺寸 layer_name 可选；旧尺寸省略时保持原几何层归属，新尺寸使用默认 DIM。图层 frozen 缺省 false，旧档案无需改写。默认 DIM 在 UI/首次新 DIM 标注时创建，不改写旧命令原参数。新图层命令可记录标注层默认值及批量迁移，均不改变几何求解约束。

不采用仅草稿图层扩展：它无法统一隐藏已有标注。不采用把标注几何移动到 DIM：尺寸归属应独立于几何。实现留给构建者：沿用 PySide6，图层表格提供独立开关、冻结和锁定列，非模态操作；只扩展当前全局图层，不引入布局视口专属 VP Freeze。

官方依据：AutoCAD DIMLAYER https://help.autodesk.com/cloudhelp/2025/ENG/AutoCAD-Core/files/GUID-88E56602-EADC-4C68-93B4-93E7623BEB6B.htm ；图层规则 https://help.autodesk.com/cloudhelp/2025/ENG/AutoCAD-Core/files/GUID-6B3E3B5D-3AE2-4162-A5FE-CFE42AB0743B.htm 。
