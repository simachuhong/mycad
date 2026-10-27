# P2-07｜当前网格缓存与历史网格按需生成

## 结果

- `BuildKernel.viewport_data()` 只返回当前模型网格（空文档仍为 `()`，成功但为空的模型仍返回一个空网格快照）。
- `ViewportPort` 增加轻量历史 ID 与单项历史网格读取：`viewport_state_ids()`、`historical_viewport_data(state_id)`。
- 当前网格缓存键含缓存世代、几何修订和归一化后的线性/角度容差；当前网格最多保留 4 组容差结果。
- 历史网格只在请求对应状态时生成，LRU 最多保留 16 项；历史缓存键含缓存世代、该状态几何修订、状态 ID 和两种容差。
- `reset()`、撤销/重做所走的重放重置、`replace_state_from()`（打开文档提交）清空缓存；每次成功几何命令递增修订并清掉当前网格缓存，旧历史状态的缓存可在 LRU 内继续复用。
- 视口刷新只取当前网格及历史 ID；树项点击仍立即预览，但仅提取所点历史网格。选择、重复刷新和着色/线框显示切换不会遍历并重新三角化所有历史。
- 未改 `.mc.json` v1，也未增加持久化 BREP 检查点。

## 10/25/50 孔性能样本

环境：Intel Core i7-7500U、x86_64、Python 3.12.3。样本为 180×120×10 mm 底板，半径 2 mm、高 20 mm 的圆柱切孔，中心按 11 列、X 间距 15 mm、Y 间距 20 mm 排列。每种孔数建模后独立测量 3 次；首次当前网格与单个历史预览报告三次中位数，缓存重复读取报告 15 次读取的中位数。

| 孔数 / 命令数 | 改前：全历史网格读取中位数 | 改前：全历史 / 当前三角形数 | 改后：当前网格首次读取中位数 | 改后：重复当前读取中位数 | 改后：中间历史预览中位数 | 改后当前 / 历史三角形数 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 10 / 11 | 337.6 ms | 10,912 / 1,972 | 59.050 ms | 0.0024 ms | 31.673 ms | 1,972 / 992 |
| 25 / 26 | 2,149.4 ms | 64,012 / 4,912 | 163.678 ms | 0.0022 ms | 67.285 ms | 4,912 / 2,364 |
| 50 / 51 | 8,265.0 ms | 250,512 / 9,812 | 381.032 ms | 0.0030 ms | 169.644 ms | 9,812 / 4,912 |

改前数据取自 `.omo/plans/phase2-agent-loop.md` 中同机器、同 10/25/50 孔样本的 P2-00 基线；其指标是 `viewport_data()` 全历史提取三次中位数。改后首读只包含最终模型网格，不是全历史耗时；历史预览一列测量按需读取一个中间状态。每次试验网格化调用数均为：当前首次 `1`、随后 5 次当前读取 `0`、单项历史预览 `1`。三种样本的最终三角形数与基线一致。

## 验证

- `uv run pytest tests/geom/test_viewport_snapshots.py -q`：13 passed，覆盖当前与历史缓存命中、不同容差、4 项当前缓存上限、16 项历史 LRU 淘汰和 reset/replace 失效。
- `uv run pytest tests/geom tests/core/test_viewport_protocol.py tests/ui/test_viewport.py tests/ui/test_picking.py tests/app/test_open_atomic.py tests/test_layering.py -q`：173 passed；包含完整 `tests/geom`、视口协议/UI、打开文档原子性和分层守卫。
- 修改路径 Ruff check 与 format check：通过。
- `uv run basedpyright src/mycad/geom src/mycad/core src/mycad/ui`：0 errors、0 warnings、0 notes。
- 首次 TDD 红路确认旧实现每次读取都会三角化全历史；加入缓存与按需 API 后上述测试转绿。代码审阅未发现阻塞项，审阅提出的缓存容量覆盖缺口已补成两条 LRU 行为测试并通过。
