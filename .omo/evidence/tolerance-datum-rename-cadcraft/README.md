# CADCraft 基准块改名交换实证

使用 CADCraft CLI 0.20.1（发行包来源及校验见相邻 `tolerance-cadcraft-2026-11-18/README.md`），在隔离配置目录执行。MyCAD 生成 `source.dxf`：共享布局基准 A，ID 为 32 个 `a`，原框 8×5；一个位置度公差框引用该基准，ID 为 32 个 `b`。基准 INSERT 句柄为 `49`，其块 `MYCAD_DATUM_0` 内单个 TEXT 句柄为 `48`。

执行的三个命令依次为：

```text
bedit {"name":"MYCAD_DATUM_0"}
lisp {"code":"(progn (setq e (entget (handent \"48\"))) (entmod (subst (cons 1 \"B\") (assoc 1 e) e)))"}
bclose {"save":true}
```

随后另存为 `block-edited.dxf`。CADCraft 返回块编辑和保存成功，LISP 返回该 TEXT 的值 B。独立用 ezdxf 核对结果：块 TEXT 为 B，INSERT 上 `MYCAD_DATUM` 扩展数据仍存在；MyCAD 导入保留基准 ID、位置、框尺寸和 B 标签，公差框仍显示旧标签 A，解除原基准身份引用并报告。定向回归为 `tests/formats/test_dxf_geometric_tolerance.py::test_cadcraft_block_edited_datum_retains_value_and_unlinks_old_reference`。

- `source.dxf` SHA-256：`46e8904e6bf73ae64d481b081585ffac15e95eb85e08516e2e860211dae4ce47`
- `block-edited.dxf` 及测试夹具 `tests/fixtures/dxf/cadcraft-datum-renamed.dxf` SHA-256：`4bec3ba2796951636b1ca64d5917861087dfcf31ed31ce93869ff5cd02b97a17`

此证据限 CADCraft 0.20.1 的命令行块编辑器及该图纸；不能证明 AutoCAD、GUI 编辑或其他 CAD 均会保留扩展数据。此前直接对块内部句柄 `handent` 而未进入块编辑器返回 nil；该尝试未修改输入，产生的无效输出已删除。

## 默认颜色与图形界面

同一源文件在 CADCraft 0.20.1 的深色 GUI 中缩放至范围后，基准和公差框几乎不可见（`gui-source.png`）：原 DXF 的图层 0 除 ACI 7 外还写入真彩色 `#282E34`，后者覆盖了自适应色。CADCraft 保存后 ACI 由 7 变为 250，但真彩色不变；根因是源文件真彩色，不能将此问题归因于 CADCraft 另存。

修复后的 `source-adaptive.dxf` 对默认图层写入 ACI 7 且不写真彩色；相同 CADCraft GUI、深色背景及缩放范围下，`gui-source-adaptive.png` 可清晰看到基准框、箭头和公差框。CADCraft CLI 另存的 `source-adaptive-cadcraft.dxf` 仍为 ACI 7、无真彩色，MyCAD 导入保留默认图层颜色、基准和公差框关联。验证使用隔离 Xvfb 桌面和 CADCraft 自带 MCP 截图接口，不等于用户真实桌面或 AutoCAD 验收。

- 修复前截图 SHA-256：`a9ee33972e064d5bb0b79f04c8930a9992d34526f235c8e60cebe545045e3a64`
- 修复后截图 SHA-256：`a1df5b18c3ef58d9918f09c69177d41c0f217e4204321fb8958f90137dcc8e88`
- 修复后源文件 SHA-256：`93b479c632cceafcf1e288b336caf90215f50466cb1f529b201d994853b129cd`
- CADCraft 另存文件和夹具 `tests/fixtures/dxf/cadcraft-adaptive-annotation.dxf` SHA-256：`d350703cb1a3728eda980aa10dfec5d7c65bcacf55cd4e7a3d254dafd1fb0685`
