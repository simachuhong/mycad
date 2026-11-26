# 基准文字样式 DXF 外部另存验证

使用项目桌面导出脚本 `capture.py` 生成 `after.dxf`，基准 B8 的原样式 ID 为 `wide`、字体 DejaVu Sans、字高 5.5、宽度因子 1.8。使用 CADCraft 0.20.1 Linux 命令行执行：

```text
cadcraft-cli convert after.dxf resaved.dxf
```

MyCAD 直接读回 `after.dxf` 时恢复原样式身份。CADCraft 另存后保留基准身份及字体族、字高和宽度因子，但把字体文件字段由空改为 `DejaVu Sans`；MyCAD 因此提示样式快照与原生字体不一致，并采用独立的原生样式。另存样本同时保存为 `tests/fixtures/dxf/cadcraft-datum-style-snapshot.dxf` 供回归测试。

```text
3c9655e7438ab0b96e404926cc9a7c53d1a4ea55cfe7853e01aec207cab51257  after.dxf
7dcf56fed7ab25000f2c067a07400ac2159fc388462f3a810a6c8a9040edb496  resaved.dxf
```

该结果只覆盖上述版本的命令行转换，不代表 CADCraft 图形交互或 AutoCAD 的行为，也不替代 GB/ISO 专业复核。
