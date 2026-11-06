# N3 E2：持久命令身份与重放事务分析

日期：2026-11-02。基于 `ba2f539` 加现有工作树及 [E1 证据](../../.omo/evidence/n3-e1-reference-probe-2026-11-02.md)。状态：候选设计与任务分析，未实施或批准新的存档 ADR。

实施补记：用户随后明确授权 E2-A 开发，已按命令记录内 instance_id 方案实施并形成 [ADR-014](../adr/ADR-014-command-instance-identity.md) 和 [验收记录](../../.omo/evidence/e2a-command-identity/acceptance.md)。随后授权的 E2-B 已采用向后兼容的 hole@3 及仅绑定分支要求 v5 的方案，见 [ADR-015](../adr/ADR-015-bound-face-hole.md) 和 [E2-B 验收](../../.omo/evidence/e2b-bound-face-hole/acceptance.md)。下文为决策前分析，E3 仍未实施。

## 推荐结论

E2 先做 **E2-A：版本化命令实例身份贯通存档、Bus、预览和内部重建**；随后 E2-B 才接入绑定面与局部孔定位。推荐在新版本（候选 v5）的每条命令中增加 `instance_id`，不再优先采用原草案的顶层平行 UUID 数组。旧 v1～v4 命令六字段与 amendments 规则保持原样；新字段是身份元数据，不取代任何审计字段。

这项建议来自现有源码的生命周期结构，不来自对 Solid Edge 私有格式的推测。E1 证明有限几何映射可行，没有证明命令实例身份、事务或跨会话引用。

## 为什么调整表示方案

| 方案 | 优点 | 代价与判断 |
| --- | --- | --- |
| 顶层 `command_instance_ids` 平行数组 | 新版本中可保持 commands 条目外形不变 | 每次 pop/append、redo、编辑、迁移和候选复制都须维护两个同步容器。当前 redo 只保存 ExecutedCommand；容易出现条数相同但身份错配。可实现，但不是首选 |
| **新版本命令条目内 `instance_id`** | 身份随同一命令的 deepcopy、dataclasses.replace、undo/redo 和事务快照传递；人工检查命令和身份也更直接 | 新版本专属校验及序列化必须显式实现；不能直接让 v1 validator 接受新字段。推荐 |
| 把 UUID 塞入 params、ordinal 或哈希派生身份 | 表面上少改存档外壳 | params 是建模输入，需侵入所有命令 schema 和插件；ordinal 会随历史调整变化，内容哈希会随改参变化且同形命令可重复。排除 |

内存里可为 ExecutedCommand 增加可选的中立实例 ID 字段，None 只用于尚未升级的旧文档；v5 活动命令不得缺失、重复或格式非法。不要把该 ID 替代 FeatureId/TopologyId：前者是命令实例，后两者继续遵守现有运行期过期契约。

## 源码中必须贯通的路径

| 入口 | 当前实现 | E2 要求 |
| --- | --- | --- |
| `core/document.py::_replace_command_params` | replace 现有命令、追加 amendment | 保持 instance_id，不改原 timestamp |
| `core/bus.py::undo/redo` | 把 ExecutedCommand 进出 redo 栈 | 同一实例撤销重做不重新分配 ID；撤销后新建得到新 ID |
| `core/document.py::_snapshot_state` | 复制命令、元数据、named_groups、dirty、archive_version | 身份分配/升级必须与这些状态及 Bus redo 栈同一事务恢复 |
| `app.py::preview_command_with_sketches` | 通过 execute 将旧命令逐条作为新执行加入 scratch 文档 | 改为保留原记录和身份的隔离重放；预览候选命令使用暂存身份，不消耗真实文档状态 |
| `app.py::copy_app_document` | 明确写死 `archive_version=4` | Save As 保持 v5，不降级；新 file_id、内部实例 ID 保持，写入成功才替换会话 |
| `core/persistence.py` | 组装 v1 payload 后逐级包装，解析时重建 ExecutedCommand | 新版显式读写 instance_id；保存、读取、reference_locations 注入后的校验均版本分派 |
| `core/document_references.py` | from_mapping 硬调用 validate_archive_v4，校验原始快照 fingerprint | 支持明确版本组合，原样保留快照身份和指纹；加载不得偷偷迁移来源再重算指纹 |
| `core/handlers.py` / `core/kernel_protocol.py` | 上下文有命令版本，但 kernel.apply 只有 id/params | 引入中立执行上下文通道；身份与版本到达几何重建路径，不能仅加 DTO 字段 |
| `geom/kernel.py` | `_operations` 仅存 id/params；草图再生直接调用 `_apply_operation`；reference.update 另起 candidate 重放 | 所有操作缓存和内部重建保留上下文，候选替换保持对应关系；绕过上下文的路径须覆盖测试 |

另外，`persistence._require_command` 当前只核对注册版本和 handler，未比较外层存档版本与 spec.min_archive_version。新增需要 v5 的命令时，必须在执行前拒绝它被装入旧格式，而非在读取时悄悄升级。

## 建议的生命周期契约

1. **旧文件读取与普通保存**：不分配持久 ID、不改变旧文件版本、不改写原审计。旧文件并不因为安装新版软件就自动获得绑定语义。
2. **启用身份能力**：在隔离候选中为当前活动命令及既有 redo 命令分配实例 ID；候选绑定描述使用这组 ID。预览取消时丢弃候选。确认时核对原文档修订、采用的身份分配及候选参数，整体提交，不能确认后再随机分配另一组 ID。
3. **首次执行及批处理**：新实例身份在对应 handler 执行前确定并进入上下文；只有整个事务成功才发布。失败恢复旧历史、身份、redo、dirty、格式版本和几何。事务中分配但未提交的 UUID 可以废弃，不要求重复执行产生相同随机字节。
4. **改参/重放/撤销重做**：对已有命令复用存储的 instance_id；runtime topology generation 仍失效并重建。重放期间不生成新实例身份。
5. **降级**：升级后的文档不因撤销绑定特征就自动降回旧格式，防止 redo 中仍存在的新式引用失去解释环境。暂不提供有损降级导出。
6. **Save As**：新 file_id；文档内部相对实例引用与实例 ID 保持。来源图中的外部引用继续指向原文件，遵守 ADR-013。不能仅凭同 UUID 判断不同文档的实例相同。
7. **副本与预览**：隔离预览属于同一逻辑文档的候选状态，可保留实例 ID，但拥有独立 runtime document_id/kernel；预览引用禁止与主视口运行期拾取混用。真正复制/另存产生新文件身份；简单复制命令作为新特征则分配新实例 ID。
8. **解析作用域**：内部绑定按当前文档解析；引用另一文档的快照时先进入该来源的独立重放环境。不得把来源 command ID 直接塞进宿主引用表。此阶段不增加跨零件面绑定。

## 新版本与嵌套快照

v5 命令记录可先校验身份字段，再用移除该新增字段后的副本复用旧审计规则；这是新 validator 的组合，不是修改旧 wire contract。复用旧 validator 时仍须保持 v5 专属字段、不支持键、文档种类和嵌套引用的严格检查，不能在运行期丢弃身份再重放。

建议版本矩阵：v4 外层只接受原有 v4 来源；v5 外层允许 v4/v5 来源。v4 引用 v5 必须先显式升级外层；旧来源快照按采用时原貌保存，不自动升级。升级后文件仍是命令历史 JSON，不能加 BREP 快照作为身份修补手段。

新文件同一时刻可嵌套不同版本的来源，因此统一的 archive-version dispatcher 要在顶层、引用快照、存盘前校验及候选加载使用。循环检测仍按 file_id，实例 ID 唯一性只在各自文档内检查。损坏的嵌套身份或 fingerprint 必须在影响当前会话前被拒绝。

## 命令版本与插件的处理边界

`CommandRegistry.get()`、命令列表和 CLI 别名都默认选最高版本；`feature.hole@2` 已同时接受直接孔和草图孔。原草案“新增版本但不改变默认选择”需要改变现有注册表政策，不能作为小细节直接实施。

**E2-A 不增加 hole 新版本、不改最高版本政策。** 先把身份能力做成明确可启用的文档/执行基础设施并测试。E2-B 再选择消费者入口：候选方向是向后兼容的新版 hole schema，明确绑定分支的最小存档要求；需要解决 spec 当前只有静态 min_archive_version 的限制，或公开接受该新版所有执行都需 v5 的成本。不能隐式按参数试错派发多个旧版本，也不能抢占新的保留命令 ID。

上下文通道建议采用新能力接口并保留旧 `Kernel.apply(id, params)` 的兼容入口；内置 v5 路径必须走带上下文入口，旧插件/fake kernel 不能被迫在无关任务中一起升级。旧接口产生的几何若无法提供 lineage，应标记该段不支持绑定，而不是伪造来源。插件是否支持可绑定输出必须明确；UUID 的存在并不代表插件能产生语义角色。

## 可独立验收的下一项：E2-A

交付：新格式的候选 ADR、身份 DTO/校验、Bus 事务传播、隔离预览、Save As、嵌套快照及内部重建上下文。没有面解析消费者时，只能声明持久命令身份基础完成。

| 验收组 | 必须验证的行为 |
| --- | --- |
| 格式 | v1～v4 fixture 保持原规则；v5 缺失/重复/非法 ID 拒绝；旧格式不能含新字段或需要 v5 的命令 |
| 生命周期 | execute、edit、undo/redo、失败批事务和打开失败；审计字段原值、身份、redo 与几何一起正确恢复 |
| 升级 | 有 redo 时升级、确认采用同一组候选 ID、取消不变、升级失败不留下半升级状态 |
| 预览 | 重复预览不重新命名已存在命令；预览失败/取消不修改主文档；主文档修改使旧确认过期 |
| Save As | v5 保持版本，新 file_id，内部 ID 保持；失败不替换会话、不改变当前路径/clean 状态 |
| 嵌套 | v5→v4、v5→v5、v4→v5 拒绝或显式升级、循环、损坏 ID、指纹不匹配、来源丢失后离线重放 |
| 内部重建 | 草图更新、reference.update、打开后继续建模与 candidate 替换都传递同一实例身份及命令版本 |
| 扩展兼容 | 旧插件和现有 test kernel 继续运行；缺少新能力时明确拒绝绑定消费者；保持分层与零抑制 |

实施顺序：先身份与文件校验 → Bus/redo/升级事务 → 预览与 Save As → 嵌套来源及几何内部上下文 → 定向验证与审阅。每步新增反例先失败，验证按 AGENTS.md scoped 四门；全量只在最终集成。

E2-B 的真实几何消费者、E3 的可视修复和 Solid Edge 实机对照仍待实施。当前报告只做源码分析；没有新跑产品测试、修改产品代码或采纳存档 ADR。
