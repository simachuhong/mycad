# P2-02 — 命令历史与审计深层隔离

日期：2026-10-23；分支 `codex/phase2-foundation`；基于 `9ab55ac267ffb6ef19fa45321b027048ef7782b2` 的工作区改动。

## 改动与行为

`Document` 在构造、Bus 追加/恢复、公开历史读取和改参返回处深拷贝命令及嵌套 JSON。
改参记录单独拷贝新参数与 `amendments.from_params`。保留 DTO、Bus、v1 和审计字段接口，
外部对象仍可编辑自己的副本，但不能旁路改变已提交历史、dirty 或重放输入。
未增加网络、后端依赖、类型抑制或新命令。

## 验证

- 有效 schema 的反例先运行：构造入参、公开历史、改参入参/返回值、handler 保留参数四例失败，
  正常编辑/撤销重做/保存重开一例通过（4 failed, 1 passed）。更早测试草稿误用 profile.kind，
  已按实际 schema 修正为 profile.type 后重新取得上述有效红灯，不把夹具错误算成缺陷证据。
- 修复后 scoped 测试共 106 passed，42.60 秒，覆盖 Document/Bus/存档/视口/拾取/分层。
- 全树 Ruff、format（194 files）、basedpyright 通过；最终集成测试结果见本批 [验证报告](phase2-foundation/verification.md)。
- 参数字典及嵌套列表、历史审计均保持隔离；正常 Bus 改参仍追加审计，原 timestamp 保留，保存重开相等。

## 限制

公开读取完整历史现在包含深拷贝成本。选择防御性复制以保持已有 dict/list API 和序列化兼容；
后续性能预算由 P2-09 实测，不能为了省复制重新暴露可变别名。未宣称修复全部失败恢复或版本派发。
