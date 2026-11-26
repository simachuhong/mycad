# 二维文字与字体设计

用户在技术路线评估后授权开发至可进入单元测试。范围为独立二维草图的 TEXT、MTEXT、STYLE、系统字体枚举、应用字体导入、特性编辑、常用变换、跨文档复制、撤销重做、保存重开以及 DXF 双向交换。后续公差、块、炸开及填充不在本次实现范围。

## 路线

采用独立文字对象、文档级样式、Qt 排版和原生 DXF 交换。扩充工程图 DrawingNote 会混淆 sheet_id 与模型坐标；首批完整 SHX/复杂富文本引擎成本过高。因此保留工程图原模型，提取可复用字体及布局服务。普通文字不参加约束求解、区域识别或三维轮廓生成。

## 数据接口

新增 core/drawing_text.py：不可变 TextStyle(style_id='standard', name='标准', font_family='', font_style='Regular', font_file='', height_mm=3.5, width_factor=1.0)；TextStyleTable(styles=(TextStyle(),), current_id='standard') 提供 get(id)、current、to_mapping/from_mapping；DrawingText(text_id, text, position_mm, kind='text', style_id='standard', height_mm=None, width_factor=None, rotation_deg=0.0, align='left', box_width_mm=0.0, line_spacing=1.0, layer_name='0')。align 支持 left/center/right（基线）以及 top_left/top_center/top_right/middle_left/middle_center/middle_right/bottom_left/bottom_center/bottom_right。所有对象提供严格 JSON mapping 往返。文字 ID 为 UUID 字符串；style_id 为稳定非空可打印标识。字高/宽度因子 None 继承样式；MTEXT 首批统一字体、换行、自动换行、行距及对齐，不承诺局部富文本、分栏、堆叠和 SHX 绘制。提供 effective_text(text,styles) 解析继承值，和 move_text/rotate_text/scale_text/mirror_text 纯变换（必要时镜像保持可读）。

新增 drawing.text.add/update/remove、drawing.text.batch（add/update/remove 三数组，optional styles 为完整样式表）、drawing.text_styles.set 命令。每次命令严格校验，批量全有或全无，变更只通过 Bus；文字仅用于 document_kind=sketch 的 drawing2d，不放宽工程图门控。内核属性 drawing_texts: tuple[DrawingText,...]、drawing_text_styles: TextStyleTable。状态参与 reset、候选复制、回滚、重放；图层设置不能删除被文字使用的图层。样式删除不能留下悬空引用。

## Qt 服务

ui/font_manager.py：FontManager(directory: Path|None=None)，families()、import_font(path)->tuple[str,...]、load_imported()、resolve(style)->QFont、font_file(style)->str、missing_glyphs(text,style)->str。QStandardPaths 下的用户目录持久存储导入 TTF/OTF/TTC；hash 去重，Qt 注册失败时回滚新文件；不安装系统字体。字体请求保留，回退仅在渲染侧发生。

ui/text_layout.py：layout_text(text,style,manager)->TextLayout，结果 bounds: QRectF（文字局部坐标，x 向右 y 向下，mm），draw(painter)，missing_glyphs: str；QPainter 在外层处理模型位置、旋转和视图缩放。字高按 capHeight 标定，宽度因子和换行共用布局，命中与绘制使用同一结果。编辑器使用覆盖式原生 Qt 控件，预编辑不进命令历史，提交一次形成一次文档操作。

## 交换和剪贴板

DXF modelspace 写入 TEXT/MTEXT，STYLE 使用字体文件标识。支持纯文字文档（无草图）；导入结果携带 texts/text_styles 并在同一操作内接受。普通内容必须转义格式码；未知或不支持格式给警告。原生 DXF 属性是交换真相，不用自定义数据覆盖外部修改。DXF 不嵌入字体，换机可能替代。Qt 字体族与文件名显式映射。剪贴板携带被使用样式，以稳定 ID 重映射解决目标冲突，不改变已有对象。

## 边界与验收

CLI/菜单/工具条入口，双击编辑，图层行为，特性字段，移动复制旋转缩放删除与撤销，保存重开、跨文档剪贴板、DXF 原生交换。字体资源操作与模型重放分离，缺字体不阻止保存/打开。后续尺寸/形位公差复用字体度量，形位符号采用独立结构化/矢量表达。

所有 PySide6 导入留在 ui；core 禁后端/numpy，零类型忽略，新增 src Python 文件保留 SPDX。验证严格遵守用户增量成本规则；不跑全量测试。先做子项开发验证，到正式单元测试入口时报告实际证据和剩余验证范围，不声称完整验收。
