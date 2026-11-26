# 外部 DXF 样本

`ezdxf-angular-tolerance-r2013.dxf` 由 ezdxf 1.4.4 的
[`dimension_angular.py`](https://github.com/mozman/ezdxf/blob/a5a2eb642f8b2bac31414f9a06bed398d276883b/examples/render/dimension_angular.py)
中的 `angular_units_tol_limits()` 生成，源脚本及项目采用 MIT 许可证，见
`LICENSE-ezdxf.txt`。脚本 SHA-256 为
`63d8f04bb073ad056913801f312fbe0c9bf72b8f626f0cedeab6b192792696be`，
生成文件 SHA-256 为 `e4e55e12ef3803ae366b522bdfa9fafe297a1180eb3c51e1425adb88e5734608`。

样本由独立示例脚本生成，并非其他 CAD 软件交互创建或编辑的文件。
样本含四种角度单位显示设置、偏差和极限尺寸，以及四个反角；文件的 `$INSUNITS`
为米，测试为了按示例数字直接比较几何坐标，显式覆盖为毫米。当前读取为十进制度
数值，公差值按原角度单位换算为度，其他角度单位的显示格式不保留。

`cadcraft-0.20.1-multiline.dxf` 由 CADCraft 0.20.1 的 `tolerance` 命令生成，
含双行、直径、M/L 和 A/B/C 基准。生成方式、版本、发行包散列及局限见
[独立软件验证记录](../../../.omo/evidence/tolerance-cadcraft-2026-11-18/README.md)。
文件 SHA-256：`b1893beff30a0a06ddcff53cb29fbff7d4d386a03e076fc8eeff5207fbe4f816`。

`cadcraft-dimension-created.dxf` 和 `cadcraft-dimension-edited.dxf` 分别由
CADCraft 0.20.1 创建与编辑尺寸公差得到，生成参数和散列见上述独立软件验证记录。
前者以不关联的参考尺寸导入；后者验证 MyCAD 可恢复外部修改的有符号偏差和原几何引用，
但 CADCraft 重排默认文字位置，MyCAD 导入时保持自动定位并提示。

`cadcraft-angle-edited.dxf` 是 CADCraft 0.20.1 修改 MyCAD 角度尺寸的输出，
原生公差使用弧度显示单位；生成参数、散列、显示裁切和导入限制见上述独立软件验证记录。

`cadcraft-moved-frame.dxf` 是 CADCraft 对 MyCAD 导出的原生双行公差框执行移动后
保存的输出，SHA-256 `bd29b465a7e66cea25b68bd08a5acd40c13a3b8f7b272f3cc5eae70b8741c01f`；
与独立软件验证记录中的 `moved.dxf` 相同，用于事务和存档测试。

`cadcraft-frame-edited.dxf` 为 CADCraft AutoLISP 修改 MyCAD 双行公差框数值后的输出；
SHA-256 `958169e1b9942885e4da67ff6576dd1ff3d4fd3ba63b5e8f8cf29e1c16e2d34b`。
第三方操作未保留该对象的 MyCAD 扩展数据，基准文字保留但引用未关联；验证记录见上。

`mycad-leader-cadcraft-source.dxf`（SHA-256 `7560f3d9cbf4e741c8efbb553dfbe3b65b843c92212b379bfed00f885a24f308`）是 MyCAD 创建的公差框和 LEADER。CADCraft 0.20.1 对句柄 `3E` 执行 `move {"handles":["3E"],"delta":[1,0]}` 并保存得到 `cadcraft-leader-moved.dxf`（SHA-256 `72a763bca96a6522566216ec3bd6c25f1f99d426e41be65e7dd8c757cc874e79`）。输出保留 MyCAD 扩展数据，移除了 LEADER 的原生关联句柄；仅供验证唯一身份恢复及消歧，不代表 AutoCAD GUI 行为。

`cadcraft-frame-independent-leader.dxf`（SHA-256 `58eb4b826b2416d6998e1e03c592b4964288dd61b1feddc4d2f711fd671d127f`）由 CADCraft 0.20.1 在空白毫米图纸中分别执行 `tolerance {"at":[20,20],"symbol":"position","tol1":{"value":0.1}}` 与 `leader {"points":[[0,0],[20,18]]}` 创建。TOLERANCE 和 LEADER 各自独立，LEADER 无原生关联句柄、无 MyCAD 扩展数据；用于验证独立引线图形保留及不猜测关联。

`cadcraft-frame-attempted-link.dxf`（SHA-256 `fa07676eeba8f2a7c5631bd4eda56bfea66e75cd2b0fb3fde6c15e814f12417e`）由 CADCraft 0.20.1 对上述独立样本执行 `(entmod (append (entget (handent "101")) (list (cons 340 (handent "100")))))` 后保存。命令返回了含 340 的实体列表，但经 ezdxf 核对保存结果的 LEADER 不含原生关联句柄；用于验证不据位置猜测关联。

`cadcraft-short-leader-resaved.dxf`（SHA-256 `b720b7dc111295d2953ade6f5dec25e43a38d2190691ee2eb06b62e5310e0306`）是 CADCraft 0.20.1 读取并另存 MyCAD 的 1 mm 短公差框引线；保留原生箭头尺寸和顶点，但移除原生关联句柄。生成和渲染记录见 `.omo/evidence/tolerance-short-leader-cadcraft-2026-11-19/README.md`。

`cadcraft-two-line-reflex-resaved.dxf`（SHA-256 `b9e9f73e8f5d302ba8fe0244bad7e3854a5bc5fe0af432d43e1493b26576bce4`）是 CADCraft 0.20.1 打开并另存 MyCAD 的 270° 两线参考角与偏差尺寸；身份、名义值和偏差可恢复。SVG 中偏差文字拥挤，不能视为外观通过；生成步骤和截图见 `.omo/evidence/tolerance-reflex-cadcraft-2026-11-19/README.md`。

`cadcraft-two-line-reflex-edited.dxf`（SHA-256 `d52ce8fd7911b34378818ed247d592039270e21b351d292679073d78305f6b64`）由 CADCraft 0.20.1 CLI 修改上述两线反角的公差字段后保存。MyCAD 可恢复 ID、270° 和 +0.30°/-0.40°；该文件重新生成的图形只显示名义值，导入会提示。生成步骤及截图见同一证据目录。

`cadcraft-straight-angle-resaved.dxf`（SHA-256 `49e07d7eb29a068e29f8363dfc9e611a30befdd1fe8b14a279a82ad7a5f567e8`）为 CADCraft 0.20.1 CLI 打开并另存的 MyCAD 180° 下半圆三点参考角；生成和截图见 `.omo/evidence/tolerance-straight-angle-cadcraft-2026-11-19/README.md`。

`cadcraft-straight-angle-edited.dxf`（SHA-256 `b6da7d69a4dab4b30abf95b6ca6de1f6eea7c5196822975318d91c5b986260b8`）由 CADCraft CLI 将上述下半圆公差改为 +0.30°/-0.40° 后保存；MyCAD 恢复结构数据并提示源图形只显示名义值。

`cadcraft-independent-reflex.dxf`（SHA-256 `62c72e3c11b8ab701cad5b84682474c2ac378be25ff9580f62017cb2d5656ea1`）和 `cadcraft-independent-straight.dxf`（SHA-256 `696406f359a3330b79af9171fcb886fb74fb4dd6200c51c5a6e4214bc43988a4`）由 CADCraft 0.20.1 在空白图纸中独立创建三点 270°、180° 尺寸并设置上下偏差；无 MyCAD 扩展数据。生成命令、图形及验证边界见 `.omo/evidence/tolerance-cadcraft-independent-angles-2026-11-19/README.md`。

- `cadcraft-datum-renamed.dxf`：MyCAD 导出的共享布局基准块由 CADCraft 0.20.1 命令行块编辑器将 A 改为 B 后保存；其 INSERT 扩展数据保留，公差框仍引用旧标签 A。SHA-256 `4bec3ba2796951636b1ca64d5917861087dfcf31ed31ce93869ff5cd02b97a17`。生成命令、原始样本及范围见 `.omo/evidence/tolerance-datum-rename-cadcraft/README.md`。

- `cadcraft-adaptive-annotation.dxf`：MyCAD 使用自适应 ACI 7 导出的基准与公差框，经 CADCraft 0.20.1 命令行另存。保留图层 0 自适应颜色及基准关联。SHA-256 `d350703cb1a3728eda980aa10dfec5d7c65bcacf55cd4e7a3d254dafd1fb0685`；图形界面对比及源文件见 `.omo/evidence/tolerance-datum-rename-cadcraft/README.md`。

- `cadcraft-v27-autoroute-resaved.dxf`：当前 MyCAD 创建的算法 4 自动基准和算法 2 自动公差框，带直线附着，经 CADCraft 0.20.1 另存。SHA-256 `08d7adce7eab621c8ab697097cb542328054d71ae33a2a726fa55176955064d6`。截图、导出及限制见 `.omo/evidence/tolerance-gui-current-autoroute/README.md`。
