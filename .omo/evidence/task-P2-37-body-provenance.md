# P2-37 当前实体来源及操作输入关系

2026-10-25。按原 P2-37 多实体来源/结果关系要求追加；不是整体 P2 G 完成声明，人工验收仍待执行。

## 实现

- 中立、不可变 DTO 记录当前 BodyId 对应的历史状态/实体结果序号，以及该步骤的输入引用。生成关系不等于逐面拓扑归属；不新增存档字段、不承诺装配持久身份。
- 适配层用 OCCT IsSame（经 build123d）保留唯一匹配的未改变实体来源，不用体积/包围盒近似猜测。选定布尔目标的所有结果必须归到本次操作，即使不相交差集几何未变。复制、变换、通用阵列记录实际源/种子；布尔记录实际目标/刀具；通用操作标为步骤输入。
- 来源只随成功的几何候选安装，失败不污染；reset、undo/redo、打开候选替换均同步。尺寸修改重新生成消费特征时，用真正追加的尺寸步骤与原模型输入记录重建，避免跳过约束的临时重放索引冒充原历史步骤。
- 当前实体树展开显示来源及输入，可点击预览该历史步骤；选中实体后属性页显示相同关系。映射只使用当前完整状态序列和 Document 命令顺序，不从 state_id 解析并猜 ordinal。无映射明确不可用。旧历史 DTO 可不携带来源。
- 显隐过滤同步过滤来源 DTO；工具体保留时显示其原来源。

## 验证

- RED：新来源接口缺失，复制→布尔两个 keep_tool 分支均失败；实现后两项通过，覆盖撤销/重做/存档重开。
- UI RED：实体树缺少来源子节点；接线后覆盖来源/输入跳转、属性、映射缺失。首次绿化时发现测试未等待已有异步历史加载，修正为等待实际 history_preview_ordinal。
- 扩展：线性/环形实体阵列、未参与实体、工具在目标前的索引迁移、不相交差集、空交集失败回滚，5 passed。
- 几何/核心最终范围：`uv run pytest tests/geom/test_body_provenance.py tests/geom/test_body_operations.py tests/geom/test_body_identities.py tests/geom/test_viewport_snapshots.py tests/geom/test_sketch_constraints.py tests/core/test_viewport_protocol.py -q` → **98 passed in 46.96s，exit 0**。含已有约束后再改尺寸的真实步骤来源、undo/redo/重开、DTO 覆盖完整性和不可变性。
- UI/右栏/核心/分层组合：29 passed、1 failed。唯一失败为新增 DTO 测试夹具漏传 identity generation，并非产品错误；修正后该核心文件已在上述 98 项最终运行全绿。UI 6 项、右栏和分层用例均通过。未将失败运行记作全绿。
- 10 个变更 Python 文件：Ruff check、format --check 通过；basedpyright 最终 **0 errors, 0 warnings, 0 notes**。
- 真实 XCB 窗口截图，隔离 QSettings，临时程序干净退出 0，已肉眼检查：`phase2-g-body-provenance/boolean-origins.png`、`boolean-properties.png`。来源/目标/刀具、保留工具原来源、实体高亮和 XYZ 方向标可见。不是用户人工验收。

## 后续

对称支架及多个边修改、通用阵列的完整改参/存档场景，P2-34 特殊偏移和 P2-33 纠错场景审查、最终原范围审计/全量四门/一次新鲜审查仍待完成。
