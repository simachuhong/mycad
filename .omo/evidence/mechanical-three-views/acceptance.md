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
