# mycad-plugin-demo

MyCAD 的最小演示插件（T9c 示例）：贡献一条命令 `demo.ping`（经
`mycad.commands` entry-point，执行返回 `"pong"`）和一个只写伪格式
`TXT-SUMMARY`（经 `mycad.formats` entry-point，写一行体积摘要）。

本包**零依赖**：假定宿主环境已提供 `mycad`，绝不把主包钉进自己的
依赖。以可编辑方式安装到当前环境：

```bash
python -m pip install -e plugins_examples/mycad_plugin_demo --no-build-isolation
```

**安全提示**：MyCAD 插件在同一进程内加载，安装即完全信任其作者
（无沙箱/签名/权限强制，见主仓 README「插件与安全」与 ADR-003）。
安装任何第三方插件前请先审阅源码——包括本示例。
