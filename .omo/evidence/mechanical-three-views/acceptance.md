# 机械三视图首版验收

日期：2026-10-27。基线已按用户要求提交 `77ca873`；执行范围为批准计划 T0–T8。本文仅记录本机实际证据，最终全量门与独立审查结果在末尾追加。

## 样本与证据

| 样本/流程 | 验证点 | 证据 |
|---|---|---|
| 法兰 OD80×8、孔20、4×6 PCD50 | 第一角主俯左、1:2、点击孔径/外径标注、孔6改8、存档重开、undo/redo、DXF/PDF一致 | `tests/ui/test_mechanical_three_views.py`，t8-flange.log；桌面与输出证据见 flange-three-views.* |
| 不对称阶梯件 | 前后/左右/俯视坐标方向，不以对称方块掩盖翻转 | `tests/geom/test_drawing_acceptance.py`，t8-empty-green.log |
| 盲孔与沉孔 | 投影完整、侧视隐藏线；同轴同侧多个圆柱来源明确 ambiguous | 同上，t8-empty-green.log |
| 同轴外圆/内孔与镜像体 | 材料侧区分，径值变化后各自保留关联 | `tests/geom/test_drawing_references.py`；t8-sides-red.log → t8-flange.log |
| 圆角、斜视圆、重复孔、多实体遮挡 | 相切线、解析椭圆、歧义拒绝、整体隐线消除 | `tests/geom/test_drawing_projection.py`、`test_drawing_projection_probe.py`、`test_drawing_references.py` |
| 有理/周期/对抗样条 | 权重与曲线保留，闭曲线归一化，禁止五点采样去重丢线 | `test_drawing_projection.py`、`test_drawing_curves.py` |
| 空模型/非法命令 | 空模型创建视图失败且历史不变；缺父视图/非法UUID/未知版本原子拒绝 | t8-empty-red.log → t8-empty-green.log；`test_drawing_archive.py` |
| 三页切换与二维兼容 | 草稿/选择/相机保留、浮动面板释放捕获、隐藏页不误操作、`.my2d`仍自由绘图 | `test_workspace_tabs.py`、`test_drafting_panels.py` 及全量回归 |
| 中文/比例/文件保护 | 精确纸幅、80mm→纸面40mm、Unicode文本、矢量输出、已有文件失败不覆盖 | T7 25测试，t7-paper.pdf/png、t7-dxf-render.png、t7-paper-text.txt；T8法兰真实出图 |

## 发现与修复

- 法兰外圆与中心孔原来轴谓词相同，导致不必要的歧义；加入与半径无关的面法向材料侧，原始和镜像模型均验证。
- 空实体图纸原本可经 CLI 创建占位视图；命令层现与界面一致拒绝，空白图纸仍可创建。32项相关检查通过。
- 自定义标注层原本在输出场景丢失；现在从关联解析到画布/DXF/PDF传播。27项标注/输出回归通过。
- 沉孔的同轴同侧多候选仍按设计拒绝，不自动猜测。这是公开的首版限制。

## 交付边界

工程图是零件档案的独立领域对象，不把草图转换成纸空间，也不从工程图数值反向驱动实体。关联只覆盖已验证的有限来源谓词；没有逐面通用持久命名。相同几何的新特征替换旧特征时仍可能无法区分语义身份。长标题需用户控制长度；DXF接收端须有适当字体。DXF标注是静态文字与几何，不宣称 AutoCAD 原生关联标注。

本机 Linux 的自动 GUI 测试、X11 截图与 Poppler/ezdxf 渲染属于工程验证，不等同用户手工验收或商业 CAD 实机认证。Windows 门仍由 CI/目标平台验收；本轮未推送，未取得新 CI 结果。既有用户 MyCAD 进程未重启。

性能复测：`t8-performance.log` 中完整900边三视图 DTO 流程 **2.859 s**，1项隔离测试通过。真实 X11 测试另发现空心路径填充区误拾取外圆；多倍率拾取回归重现后已按屏幕轮廓距离修复，原失败保留在 `t8-desktop.log` 与 `t8-pick-red.log`。这是鼠标命中规则，不用于持久关联猜测。

真实桌面复测 `t8-desktop-green.log`：1项法兰全过程通过（19.48s）。`t8-pick-green.log`：20项标注/法兰检查通过。Poppler再次渲染法兰最终PDF并检查中文字、⌀8.00mm、⌀80.00mm及三视图；输出见 `flange-three-views-pdf.png`、`flange-three-views-text.txt`。当前桌面截图在重开默认3D页拍摄，须补工程图页截图以对应图中操作界面。

全量首轮：2085通过、10失败（1168.65s，`final-pytest.log`）。9项是新增9条工程图命令/3类角色/ADR012后的旧固定目录断言；已更新独立期望清单，57项专项通过。另1项旋转鼠标测试在基线77ca873临时归档中同样失败（`t8-rotation-baseline.log`），系整数像素与理想毫米中心差0.1mm。产品旋转实现未改；测试改为绕实际点击中心的精确90°结果，15项交互回归通过。没有放宽几何容差。当前还需独立审查及最终修复后门槛。

最终X11复测 `t8-desktop-final.log`：1项通过26.69s。重开后显式切回工程图页，最终桌面截图已替换并检查，显示三个常驻Tab、纸上三视图及80/8标注、右侧可浮动Tab容器、底部共享控制台。

最终静态复查：全树 `ruff check .` 通过，`ruff format --check .` 407文件通过，`basedpyright` 0错误/0警告。见 `final-recheck-{ruff,format,types}.log`。独立审查范围为基线77ca873至ee24bc6；源码冻结，待审查结果。

独立审查确认2项Important、无Critical/Minor（`final-review.md`）。已完成一轮修复：目标图纸消失时取消未提交视图预览；PDF按实际Qt排版/回退字形拒绝缺字。`review-red.log`重现两类失败；`review-green.log`19项通过；增补真实回退字体检查后`review-font-fallback.log`9项PDF检查通过。仅DejaVu的隔离Fontconfig子进程确认中文不可绘制、导出明确拒绝且原文件未改（`review-fontconfig.log`）。修复路径lint/format/type通过，最终整套回归进行中。

## 最终验收结论

**本机、已批准首版范围内的 P0/P1 发布门通过。** T0–T8 已实施；独立审查的2项Important均以RED→GREEN修复，无Critical或延后Minor。未扩大到通用拓扑命名、装配或商业CAD认证。

最终整套命令：`QT_QPA_PLATFORM=offscreen uv run pytest -q --durations=10` → **2101 passed in 1153.00s（19分13秒）**，见 `final-repaired-pytest.log`。几何/900边完整传输/UI心跳性能门包含其中并通过。全树lint、格式、严格类型复查通过；两项审查修复路径再次lint/format/type通过。

验证覆盖：模型/图纸历史隔离、有限来源关联与歧义拒绝、迟到结果防护、图中放置与手柄、撤销/重做及保存重开、1:2数值/纸面比例、中文及真实字体回退、缺字拒绝、原文件保护和旧二维工作区兼容。最终可复核界面见 `flange-three-views-desktop.png`，成图见 `flange-three-views.pdf`/`flange-three-views-pdf.png`。

保留分支 `codex/phase2-foundation` 与现有工作目录，不合并、不推送。Windows及AutoCAD/Solid Edge实机验收仍未完成；本轮现有用户MyCAD进程未重启，新功能需重启后加载。
