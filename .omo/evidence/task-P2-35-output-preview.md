# P2-35 DXF 输出预览及尺寸渲染修复

2026-10-25。原范围要求“首批提供可核对的二维输出预览”，现已补齐内置 DXF 的预览/确认路径。

## 实现

- 复用 ezdxf 官方 Drawing/SVG 后端，渲染实际准备输出的 DXF（含标准 DIMENSION 块）。Qt 只负责显示、缩放和平移；未另写尺寸渲染器。
- 串行工作线程生成预览。对话框展示交换报告、空白图层提示、字体差异说明；确认导出后原子写入完全相同的数据。取消不覆盖，文档 revision/session 变化拒绝旧预览；自定义格式 provider 的解析优先级保持。
- Pillow 12.3.0 增加到 desktop extra、uv.lock 和 NOTICE（MIT-CMU）；渲染器延迟导入，普通 headless DXF 写入仍不需要 Pillow。
- 实际预览发现旧角度绘制存在“测量 90°、图形文字 270°°”的不一致。根因在二线角度的绘制射线顺序及重复附加度数符号。改用标准三点角度，显式设置角度精度、十进制度及小数点；负角交换反向射线并显示负号，XDATA 保留原有向约束。
- 修复闭合多段线末段的标注索引越界；修复全部图层隐藏导致 ezdxf 空包围盒异常。

## 验证

- 新预览模块/对话框测试先因缺失而失败；接入前的三个导出流程测试失败，接入后通过。
- 七个正/负/优角尺寸用例先失败，修复后标准 DXF `get_measurement()` 与匿名块 MTEXT 读数均正确（不依赖 MyCAD XDATA 解码来验证显示值）。包含 30、90、135、270、-30、-90、-270°。
- 闭合折线末段尺寸先报索引越界，修复后通过。全隐藏图层先报 empty bounding box，修复后生成空白预览并保留原 DXF 几何和交换警告。
- `uv run pytest tests/formats/test_dxf_output_preview.py tests/formats/test_dxf_sketch_exchange.py tests/ui/test_dxf_output_preview.py tests/ui/test_document_lifecycle.py -q`：**38 passed in 18.82s，exit 0**。上一轮虽输出 38 passed 但进程 exit 143，未按干净完成采信，异常与复跑记入 ledger。
- 交换/分层/依赖闭包/NOTICE 范围回归：**42 passed in 60.29s**（角度与末段修复前的兼容范围；新增修复由上述 38 项覆盖）。
- 本轮八个 Python 文件 Ruff/格式与 basedpyright 通过，最终新增空白预览路径另做严格类型检查通过。
- 实际 Qt 渲染截图已检查：`phase2-g-output-preview/five-dimensions.png`，配套 `.mc.json` / `.dxf` / `.svg`。示例尺寸 60 mm、40 mm、90°、R10 mm、Ø16 mm，显示值正确，选上边标注长度以避免与左下角角度标注重叠。

## 边界

自动读取与渲染使用 ezdxf 标准实体接口，不等同于 AutoCAD/Solid Edge 实机验收。本机未发现对应 CAD 程序，保留用户手工检查。没有宣称任意密集标注自动避让、尺寸拖放或关联工程图已实现。P2 G 继续保持 active。

参考：https://ezdxf.readthedocs.io/en/stable/addons/drawing.html
