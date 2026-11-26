# 公差框箭头版本 28 画布自检

隔离 Xvfb、Qt xcb 及软件 OpenGL 运行 `capture.py`，通过机械式入口创建基准及公差框。明暗画布分别显示基准宽三角形及公差框较窄的闭合实心箭头，样图同时导出 DXF。

- 明亮画布 SHA-256 `7469a9404cf9d44949d0888acd188ea9b1324817eb5fbd28c55a6303f6b1a9d3`
- 暗色画布 SHA-256 `7270013123ec6012dbd490163a387fd7a81142cb35882d93425b1da37e6135eb`
- DXF SHA-256 `21dacf4e12c0e3c5ed2861338acca5aac76570d59f01c8f9f19facfc378519d9`

CADCraft 0.20.1 CLI 对该 DXF 另存并导出 SVG；图中公差框箭头长 2.5、底宽约 0.8333，与新版画布比例相同，基准三角形底宽 2。另存文件由 MyCAD 导入后，基准和公差框对象与原文件导入结果一致；CADCraft 未保留公差框原生关联句柄，本软件依据唯一身份恢复并报告。两份 DXF 已作为定向回归夹具。

- CADCraft 另存 DXF SHA-256 `cbc5e506d8daccd3bed66d8cf1a8f9dd954255ceb7625710101ac81443a94749`
- CADCraft SVG SHA-256 `46b1cd7e0b72c7ff279251fe0c3471af03d824be01d55489dcb8a8311628e346`

脚本自动接受对话框并输入坐标，不代表真实鼠标操作、AutoCAD 实机对照或 GB/ISO 合规验收。
