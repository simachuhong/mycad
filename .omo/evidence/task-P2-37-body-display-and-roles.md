# P2-37 多实体显隐与操作角色

2026-10-25。原结构树只有当前实体编号，且建模栏只说“已选目标体和刀具体”，缺少明确的对象名称与显示控制。

## 已实现

- 当前实体树可逐体勾选显示，附加“显隐”文字列和“显示全部实体”。真实 XCB 核对发现原生 unchecked 图标不明显，因此文字状态也显示“显示/隐藏”。
- 只过滤显示 DTO：网格三角形/顶点、边界、面和顶点拾取同步过滤；重映射三角顶点索引，隐藏对象不参与点选、预选、框选及适应窗口范围。原始内核、文档历史、导出与布尔输入不变。
- 隐藏已选对象清除选择。点击隐藏实体的树节点明确要求先显示。相机不因显隐变化跳动。
- 显隐按当前运行时 BodyId 保存；同一仍有效身份保留，重建后失效身份不转给其他实体，新文档清空。
- 候选/历史预览完整显示相应模型，并明确提示退出后恢复当前显隐；预览时暂禁编辑当前实体显隐。串行工作线程忙碌时同样禁用，避免并发读取内核。
- 布尔建模栏显示“目标：实体 N / 刀具：实体 M”，随参数更新“保留/消耗”；变换显示来源、复制保留源体，实体阵列显示种子及数量包含种子。
- 成功预览给出整个候选模型的实体总数；提交回执保留操作对象、工具保留/消耗及模型总数。

## 证据

- 显隐接口测试先 **2 FAIL / 2 PASS**，实现后 **4 PASS**。
- 对象角色测试先 **2 FAIL**，实现后相关布尔/变换/阵列选择定向 **7 PASS**。
- 忙碌门禁与隐藏树提示补测先 **2 FAIL / 3 PASS**；修复后范围回归：
  `pytest tests/ui/test_body_tree.py tests/ui/test_modeling_interaction.py tests/ui/test_picking.py tests/ui/test_right_tabs.py tests/test_layering.py -q`
  **77 passed in 113.10s，exit 0**。
- 布尔保留/消耗两种路径扩展 GUI 撤销/重做/保存重开；保留路径隐藏原工具体后仍验证完整模型体积：**2 passed, 33 deselected in 16.58s，exit 0**。
- 显隐文字列先 **1 FAIL**；最后 body_tree + right_tabs **15 passed in 15.43s，exit 0**。
- 六个 Python 文件 Ruff、格式、basedpyright 全通过，0 errors / 0 warnings / 0 notes。
- 真实 XCB 全窗口截图：`phase2-g-multibody-display/all-bodies.png` 与 `body-2-hidden.png`，已视觉核对显示变化及树的显隐文字。截图进程使用隔离 QSettings，没有改写用户窗口布局。

## 执行记录与边界

首次范围命令误写不存在的 `tests/ui/test_structure_tree.py`，pytest exit 4，未执行任何测试；改为真实 `test_right_tabs.py` 等路径后取得上述 77 PASS，不把该次命令视为验证。

首次截图进程在应用退出时被正常的未保存文档对话框阻挡。仅终止自己创建的 PID 310864；修正截图脚本的临时文档 discard 回调后重新运行，干净 exit 0。没有终止或操作用户已有 GUI。

目前操作对象和结果数量清楚，但这不是跨历史的逐实体来源图谱。当前实体到创建/复制/布尔步骤的来源追踪仍待补齐，见 `docs/superpowers/plans/2026-10-25-body-operation-provenance.md`。P2 G 保持 active，尚不宣告 P2-37 或全组完成。
