# CADCraft 独立公差框交换验证

使用 [CADCraft v0.20.1 官方发行包](https://github.com/storytold/cadcraft/releases/tag/v0.20.1)，CLI 版本 `0.20.1 (7526dc62c14e71b3c8d46e73bbf1fa29ef506af1)`；Linux x86_64 tar.gz 的 SHA-256 `57b6f1b41b4f3c542a82f103202ed1a779440e5ff8d25c08ef66abda1a8cb1b9` 与 GitHub release API 的 digest 一致。只解压至临时目录，配置目录也在临时目录，未系统安装。

1. 使用 `cadcraft-cli run --metric --cmd 'tolerance {"at":[10,20],"symbol":"position","tol1":{"value":0.12,"diameter":true,"material":"M"},"datums":["A","B(L)","C"],"line2":{"symbol":"parallelism","tol1":{"value":0.08,"material":"L"},"datums":["A"]}}' --save cadcraft-created.dxf` 由 CADCraft 生成原生 DXF。样本保存在 `tests/fixtures/dxf/cadcraft-0.20.1-multiline.dxf`，SHA-256 `b1893beff30a0a06ddcff53cb29fbff7d4d386a03e076fc8eeff5207fbe4f816`。MyCAD 定向测试读取到预期两行、位置及各字段；基准标签没有对应基准对象，故为未解析引用。
2. 输入为 `../tolerance-cadcraft-gui-symbols/pre-fix-review-sample.dxf`（SHA-256 `e68df2be480b68f0184a523e4faf69b51d75e821cddc88a8d3b8af1fbbeaef87`），通过 `cadcraft-cli run INPUT --cmd 'move {"handles":["47"],"delta":[5,3]}' --save moved.dxf` 移动其中一个双行原生公差框。CADCraft 返回 `{"moved":1}`；MyCAD 重新导入后读取到位置 `(5,23)`、原两行和三个基准对象，关联 ID 保持且报告无提示。`moved.dxf` SHA-256 `bd29b465a7e66cea25b68bd08a5acd40c13a3b8f7b272f3cc5eae70b8741c01f`。
3. 对同一个实体用 `properties.set` 设置新 `text` 时，工具虽返回 `changed:1`，随后 `properties` 读出的文字仍为旧值；因此未得到有效的第三方数值编辑测试，不计为通过。

上述证据覆盖 CADCraft 0.20.1 的无界面创建与移动，不代表 AutoCAD 或其他软件的表现，也不证明标准合规、GUI 编辑或公差值修改往返。

4. 使用 `cadcraft-cli run INPUT --window=-5,0,90,40 --export cadcraft-render.svg` 渲染同一 MyCAD 原生 DXF，再用 `rsvg-convert` 将 SVG 转成 PNG 供查看。图中可见双行的位置度、平行度、直径、数值、M/L 和 A/B/C；页顶其余符号因有意选择的视窗而裁切。SVG SHA-256 `40b162b6d3087de159d0f7c75e68ae8ab5e11cd2e2b23b01e1e388ded7076c68`，PNG SHA-256 `8035dd8a65f3be8a56500a5f91439e35605362cf95e3648b91de5e0a2afbe18c`。同一工具的直接 PNG 导出在此环境下前景与深色背景对比度极低，不能计为正常显示。这个样例只证明 CADCraft 的 SVG 导出路径可见，不证明原生 GUI 显示、其他字体或标准合规。
5. 对该 TOLERANCE 使用 CADCraft `textedit` 命令会返回只支持文字、多重引线、属性定义或尺寸的错误；这与 `properties.set` 未实际更改文本的结果共同表明本次 CLI 路径未能验证数值编辑。

6. CADCraft 独立创建线性尺寸及偏差：执行 `dimlinear {"p1":[0,0],"p2":[20,0],"at":[10,5]}` 后执行 `dimoverride {"handles":["{last}"],"DIMTOL":1,"DIMTP":0.02,"DIMTM":0.01,"DIMTDEC":2}` 并保存。生成文件 `tests/fixtures/dxf/cadcraft-dimension-created.dxf` 的 SHA-256 为 `93380db8a1d4f2fb8b66ed88d10121c09977b07a2e28c25d7b5cb4050fe81a0f`；MyCAD 导入为名义值 20、上偏差 +0.02、下偏差 -0.01 的不关联参考尺寸，并报告语义边界。
7. `mycad-dimension.dxf` 由 MyCAD `write_sketches_dxf` 生成，含一条直线及名义值 20、初始上下偏差 +0.02/-0.01 的关联尺寸；实体和尺寸 ID 分别固定为 `01` 重复 16 次及 `02` 重复 16 次，尺寸句柄 `3A`。原文件 SHA-256 `ab5d6dab725dfc92602b18f1cb509a53185fc49817a7b9b12e8b64285b4b8a64`。CADCraft 执行 `dimoverride {"handles":["3A"],"DIMTOL":1,"DIMTP":0.04,"DIMTM":-0.01,"DIMTDEC":2}` 后保存，返回 `changed:1`；输出 `tests/fixtures/dxf/cadcraft-dimension-edited.dxf` SHA-256 `8e9a750333b85ba64bf1b3a68bf81dcf295e4c32bc87098483be7de5ea2db920`。经 ezdxf 核验原生字段后，MyCAD 导入保留尺寸 ID 和几何引用，上下偏差为 +0.04/+0.01，并报告外部公差已恢复及默认文字位置被重算。第三方将 DIMPOST 由缺省写成空字符串，等价于无前后缀，不再误报为未恢复修改。MyCAD 根据 DXF 70 组的 128 标志保留自动定位，不把 CADCraft 重新计算的默认中点当作手动定位。
8. CADCraft 对编辑后的尺寸导出 `dimension-edited.svg`，经 `rsvg-convert` 生成 `dimension-edited.png`。图中尺寸偏差排成一行且文字远离尺寸线，说明此交换路径的外观不能视为一致；截图仅反映该 CADCraft 版本和样例。SVG SHA-256 `7ca034cfb9949b986d9f05d98f8a0eb3183a41dffa5c7834ed7d1f73af6b385b`；PNG SHA-256 `4a3d9b6ce5cfeb6a20c4f66f60d2b4d425bfb1ed3deb6ede7a3eebd6ebdc993f`。

9. 角度尺寸交换：`mycad-angle.dxf` 由 MyCAD 写入两条相交线及 90° 参考角度尺寸，尺寸 ID 为 `33` 重复 16 次，两线 ID 分别为 `11` 和 `22` 重复 16 次，尺寸句柄 `3B`。CADCraft 执行 `dimoverride {"handles":["3B"],"DIMAUNIT":3,"DIMTOL":1,"DIMTP":0.01,"DIMTM":0.02,"DIMTDEC":4}` 并保存，返回 `changed:1`。输出 `tests/fixtures/dxf/cadcraft-angle-edited.dxf` 的原生字段经 ezdxf 核验；MyCAD 导入为十进制度偏差约 +0.5729577951°/-1.1459155903°，保留尺寸 ID 和两条几何引用，报告角度显示单位不保留；其省略的组 16 默认为零点，不再误报为未恢复的变更。三点角度的顶点在组 15。原始 DXF SHA-256 `fb82777d8f4e02002ba750c270013cb599268a902271faaa8c0bfa7f32d4c7f9`；编辑 DXF SHA-256 `64e2657a4e78e8c70f857fbbccbc7cec2b7a6aafcd22754f7cc865c89ae0fdf4`。CADCraft 执行 `--view extents --export angle-edited.svg` 后输出明显裁切，不能评为外观通过；SVG SHA-256 `d7d36638cea70729e35e3cc370d84fafde45c4dc292b4b7cc567a4043eec0e95`，经 `rsvg-convert` 生成的 PNG SHA-256 `8ef48c01c2b11a76a85e99a9b1f6d7812ee64a36fa76e9d40d0c0fb4b1875084`。此处验证的是 CADCraft 生成的字段与 MyCAD 的转换，不证明其他 CAD 的显示或修改行为。

10. 形位公差数值编辑：在本记录第 2 项的输入图纸中，用 CADCraft 的 AutoLISP `entget`/`entmod` 修改句柄 `47` 的组 1，将首行公差从 `0.12` 改为 `0.25`，其他内容不变；`properties` 实际读取到新值，再保存为 `tests/fixtures/dxf/cadcraft-frame-edited.dxf`。其 SHA-256 为 `958169e1b9942885e4da67ff6576dd1ff3d4fd3ba63b5e8f8cf29e1c16e2d34b`。此操作使用未请求扩展数据的 `entget`，CADCraft 保存结果不含该公差框的 `MYCAD_FCF` 扩展数据：MyCAD 重新导入后可读到新值、两行与 A/B/C 文本，但无法恢复原公差框 ID 和基准对象关联。导入报告提示未关联，须在编辑器显式检查并关联；不按同名自动猜测。本结果证明该 CADCraft AutoLISP 路径的数值可交换，不证明保留元数据或 GUI 编辑往返。

第 10 项 AutoLISP 核心操作如下；以 CADCraft `lisp` 命令运行后，通过 `properties {"handles":["47"]}` 核验内容，再另存 DXF：

```lisp
(setq e (entget (handent "47")))
(entmod (subst (cons 1 "{\\Fgdt;j}%%v{\\Fgdt;n}0.25{\\Fgdt;m}%%v%%vA%%vB{\\Fgdt;l}%%vC^J{\\Fgdt;f}%%v0.08{\\Fgdt;l}%%v%%vA%%v%%v") (assoc 1 e) e))
```

11. 第 10 项丢失扩展数据的实际样本在 Xvfb/XCB 下由 MyCAD UI 导入；通过公差编辑器逐行显式关联 A/B/C，验证 0.25、公差关联、撤销重做和保存重开，1 项定向测试通过。这是自动化桌面壳验证，不代替真实桌面人工验收，也不代表 CADCraft 保留了原关联。

12. 公差框引线移动：MyCAD 样本 [source](../../tests/fixtures/dxf/mycad-leader-cadcraft-source.dxf) 的 TOLERANCE 句柄为 `3D`，LEADER 句柄为 `3E`。CADCraft 0.20.1 执行 `move {"handles":["3E"],"delta":[1,0]}` 返回 `{"moved":1}`，输出 [DXF](../../tests/fixtures/dxf/cadcraft-leader-moved.dxf) 的引线顶点分别为 `(1,0)`、`(21,18)`；扩展身份保留，但原生关联句柄缺失。MyCAD 现在仅在框及引线身份均唯一时按扩展身份恢复引线并提示原生关联缺失；重复标识或其他非空句柄不恢复。源和输出 SHA-256 及命令见样本说明。这是 CADCraft CLI 的单一交换样例，并非 AutoCAD GUI 结果。

13. 由 CADCraft 独立新建的 [公差框与引线样本](../../tests/fixtures/dxf/cadcraft-frame-independent-leader.dxf) 中，两对象没有原生关联句柄；此前 MyCAD 跳过 LEADER。现导入时不按位置猜测，将平面直线及可识别箭头保留为普通图元并报告失去结构化关联。样本生成命令及 SHA-256 见样本说明；这证明 CADCraft 该命令行创建路径的独立对象导入，不证明 AutoCAD 的关联引线行为。

14. 对第 13 项中的 CADCraft 独立引线，使用 AutoLISP `entmod` 将 340 关联字段设置为公差框句柄，命令返回的实体列表含目标；但另存的 [DXF](../../tests/fixtures/dxf/cadcraft-frame-attempted-link.dxf) 中，ezdxf 读取不到 LEADER 的原生关联句柄。MyCAD 定向导入保留普通引线图形且未猜测关联。此结果仅反映该版本和该 AutoLISP 保存路径，不能证明 AutoCAD 的行为。

15. 重新检查第 9 项角度样本：原生公差字段存在，但 CADCraft 重生成的尺寸块文字仅为 `1.57r`，没有偏差。MyCAD 继续恢复关联及弧度换算后的公差，同时提示源图形未显示公差。此结论依据实体图形块及字段，并不将此前被裁切的 SVG 当作外观通过。
