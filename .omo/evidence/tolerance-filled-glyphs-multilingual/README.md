# 公差框含中文和材料修饰符的跨软件样例

`capture.py` 以实际画布字体布局生成位置度、直径、公差值、材料条件 M 和基准文字 `A基准` 的图形兼容 DXF；由 CADCraft 0.20.1 CLI 转为 SVG 和 PNG。该样例中中文及 M 使用填充字形，材料条件圆圈与格线可见；画布与第三方外观仍需人工核对，不能推断所有字符或 AutoCAD 均相同。此处中文仅用于测试字体交换，不代表合规制图示例。

SHA-256：

- `graphic.dxf`: `f1b733f49a6d0c8c1a2d9469251006864ede987d687dccab179af68d042cca22`
- `canvas.png`: `b3aad0f4953b5161815135c05414e6edde389df504e2b0b015f293756d7ddd99`
- `cadcraft.svg`: `d0367bff62906a69e41035136e4870357c3f01e4cc07b390c181b46d6232d0eb`
- `cadcraft.png`: `19f13558b99d43312ba8f5e3ef26cbd380ff5ddd8e26b2f3e4a15a85669c8b22`
