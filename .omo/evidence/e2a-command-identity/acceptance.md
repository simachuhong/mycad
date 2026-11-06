# E2-A 命令实例身份验收

日期：2026-11-02。基线 `ba2f539` 加先前未提交的 N1/N2/N6/E1 工作。本记录只评价本轮 E2-A；原有几何/场景/素材等增量保留，未提交、推送或发布。

## 交付

- v5 命令记录内新增必需的 canonical hex UUID `instance_id`；旧 v1～v4 的字段校验及序列化规则保持。实例身份随命令对象进入编辑、undo/redo 和事务快照，审计六字段和 amendment 追加语义保留。
- Bus `prepare_identity_upgrade()` 返回签名、文档身份及修订绑定的提案；准备/放弃无模型副作用。`apply_identity_upgrade(proposal)` 采用确切 ID，并覆盖既有 redo；失败恢复历史、身份、格式、dirty、redo 和几何。格式预检失败不触碰尚未重建的几何。
- 内置 handler 通过可选 ContextualKernel 传递中立 ExecutionContext。旧 kernel/apply 与插件接口仍兼容；几何操作记录、候选替换、引用更新和草图内部再生保留命令实例及版本。
- 模型预览隔离重放已有记录，保留原身份；支持显式来源格式以覆盖升级后空历史。GUI 相关预览入口传递该格式快照。
- Save As 保留 v5、内部实例 ID 及 redo，以新 file_id 替换会话；写入失败保持原会话、原文件和可 redo 状态。复制后的 Bus 使用新的确认密钥，旧授权不移植。
- v5 可采用原样 v4/v5 快照；v4 引用 v5 被拒绝并要求显式升级。嵌套身份、来源指纹和命令版本/最低格式要求在重放前预检，保留循环检测。

## 反例与审阅处置

先写测试验证缺失 upgrade API 及 kernel 上下文失败，再实现。对 stale/tampered/跨文档提案、非法/缺失/重复 ID、失败升级、失败批事务、redo 分支和旧字段规则分别做回归。

独立审阅确认嵌套 v5 无效 ID 即使指纹正确也能通过原先结构校验，直到 handler 才被拒绝。新增反例先报 DID NOT RAISE，再通过递归来源/指纹校验修复；最低命令版本也递归预检。Save As 丢 redo 的缺口先通过缺失 copy_for_document 的失败测试确认，再补 Bus 复制与真实 GUI 成功/磁盘失败测试。升级后空历史的预览先以不支持来源版本参数失败，再补显式格式入口。

最后对合法旧混合历史升级失败增加反例：原先错误地重放未改变的内核；测试禁止 reset 后确实失败。现按是否开始重建，分别恢复文档状态或恢复并重放。

旧 DTO 布局测试显式增加可选身份元数据，同时继续断言六个必需审计字段。unsupported-version 错误的 supported 字段由 4 更新为实际支持的 5。未削弱 layering、旧格式校验或增加类型抑制。

## 验证口径

1. 中途较大范围定向回归：`tests/core tests/commands tests/plugins` 加相关几何、sketch constraints、kernel version、topology、layering/scope audit：**816 passed**。
2. 文档 session/save/lifecycle/history-edit UI：**60 passed**。
3. 审查修复后，身份/持久化/文档引用与真实几何：**54 passed**。
4. 审查修复后，v5 Save As 成功/失败及 parameter forms、fillet、driving dimensions、constraint dialog：**39 passed**。
5. 最终新增功能与修复集合：**24 passed，11.48s**，见 [JUnit](junit.xml)，0 errors / 0 failures / 0 skipped。

上述集合有重叠且对应不同增量，不能直接相加作为独立测试数，也不等价于当前候选提交全仓四门或远端 T1 CI。静态检查限定本轮 19 个 Python 文件：ruff check、format check 通过，basedpyright 无错误/警告/提示；最后回滚修复及测试路径再次检查通过。无依赖变更。

## 范围和执行判断

复用包含未提交前置成果的当前 feature checkout，避免丢失拓扑原型；没有创建新工作树。按用户明确开发请求直接执行已选的 E2-A，保持旧 wire 契约；执行顺序和代码接口细节由本轮计划确定。按项目规则进行 scoped 验证，全仓测试留给阶段最终集成。

桌面默认仍用 v4。v5 当前通过显式开发 API 启用；没有新 hole 命令、可保存的面绑定描述、自动 primitive 语义角色、局部孔定位产品能力或重关联 GUI。E2-B/E3 才接入这些消费者及确认流程；不能用持久 UUID 代替逐面 lineage，也不宣称解决通用拓扑命名或完成 P2-12/19。
