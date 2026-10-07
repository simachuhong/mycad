# T7c：组合根 app.py + 集成测试 + 跨文档隔离 + 法兰 QA

你是 MyCAD phase-0 计划的 T7c 执行者。本提示词是唯一任务书，逐字执行。
计划 `.omo/plans/phase0-mvp.md` 行 350-379（T7 段 app.py 与测试小节）为权威规格。
**第一动作：`cat` 本文件已完成；随后 C0 逐项读取参考源码，禁止跳过。**

## 反停摆五纪律（每回合必须遵守）
1. 禁写清单文件/计划文件；执行清单只在脑内。
2. 单次写文件 ≤100 行（`cat >` 首批 + `cat >>` 追加）。
3. 每回合只做一个小动作。
4. 禁长推理：设计已钉死；遇规格冲突记 deviation 后选本文规则。
5. BLOCKED 立即停并输出原因。

## 白名单（仅允许创建/修改以下文件）
- `src/mycad/app.py`（新建）
- `tests/test_layering.py`（**仅**追加 src/mycad/app.py 白名单例外，禁动其他规则）
- `tests/app/__init__.py`（新建，空）
- `tests/app/test_composition.py`（新建）
- `tests/app/test_builtin_execution.py`（新建）
- `tests/app/test_flange_qa.py`（新建）
- `.omo/evidence/task-7-phase0-mvp.md`（追加 `## §T7c` 段）

**禁改**：src 与 tests 其余一切；禁 git 操作。

## 通用规则
- SPDX 两行头；basedpyright strict 零 ignore；ruff 零豁免；TDD 红绿。
- **docstring 纪律**：测试 docstring 禁出现守卫扫描字面量。

## C0 前置读（依次，禁止跳过）
1. `cat src/mycad/builtin_commands/__init__.py` + `head -50 src/mycad/builtin_commands/specs.py`（T7a 产物：COMMAND_SCHEMA_DEFS/BUILTIN_COMMAND_SPECS/BUILTIN_COMMAND_IDS）。
2. `cat src/mycad/plugins/manager.py` + `head -40 src/mycad/plugins/types.py`（T7b 产物：PluginManager/command_contributions）。
3. `cat src/mycad/commands/registry.py`（**勘察 spec 枚举 API**：search/__iter__/ids——new_document 装配 handler 映射需要遍历全部已注册 spec）。
4. `cat src/mycad/formats/registry.py` + `cat src/mycad/formats/__init__.py` + `head -30 src/mycad/formats/providers/step_provider.py`（FormatProviderRegistry 构造签名 + STEP_PROVIDER/STL_PROVIDER 导入路径）。
5. `cat src/mycad/core/persistence.py` 的 LoadedDocument 段 + `head -30 src/mycad/core/bus.py` + `head -30 src/mycad/core/document.py`（Document/CommandBus 构造签名）。
6. `cat src/mycad/geom/kernel.py`（BuildKernel 构造/reset/apply；**勘察 mode=new 语义**：apply_primitive 对 new 是替换整体还是新增 body——读 _b123_ops.py 源码确定）。
7. `cat tests/test_layering.py`（现有守卫结构，确定 app.py 例外怎么加）。
8. `cat src/mycad/commands/grammar.py` 的公开函数签名（parse_line/to_cli）。

## 钉死设计（照抄，勿发明）

### src/mycad/app.py（组合根，唯一 layering 例外）
- imports：`from mycad.builtin_commands import BUILTIN_COMMAND_SPECS, COMMAND_SCHEMA_DEFS`、`from mycad.commands.registry import CommandRegistry`、`from mycad.core.bus import CommandBus`、`from mycad.core.document import Document`、`from mycad.core.handlers import BuiltinModelingHandler`、`from mycad.core.persistence import LoadedDocument`、`from mycad.geom.kernel import BuildKernel`、`from mycad.formats.registry import FormatProviderRegistry`、（STEP/STL provider 按 C0 第 4 项勘察的导入路径）、`from mycad.plugins.manager import PluginManager`、`from mycad.plugins.types import PluginDiscoverer`。
- `@dataclass(frozen=True) class AppServices:` 字段**恰四个**（顺序写死）：`registry: CommandRegistry`、`kernel: BuildKernel`、`formats: FormatProviderRegistry`、`plugins: PluginManager`。
- `def build_app(discoverers: Sequence[PluginDiscoverer] | None = None) -> AppServices:`（#round11-NB7：discoverers=None 或 [] 时 PluginManager(()) 空发现；T9 才接真 discoverer，本片不实现 EntryPointDiscoverer）：构造 `CommandRegistry(schema_defs=COMMAND_SCHEMA_DEFS)` → 逐个 `for spec in BUILTIN_COMMAND_SPECS: registry.register(spec)`（显式 Python 注册，绝不 entry_points）→ `BuildKernel()` → `FormatProviderRegistry([STEP_PROVIDER, STL_PROVIDER])`（构造形态按 C0 勘察）→ `PluginManager(())` → 返回 AppServices。
- `def new_document(services: AppServices, *, confirmed_by: str | None = None) -> LoadedDocument:`：
  1. handler 映射：`handlers = {spec.id: BuiltinModelingHandler(spec.id) for spec in <C0 勘察的 registry 枚举>}`；再遍历 `services.plugins.command_contributions()`，`if c.handler_factory is not None: handlers[c.spec.id] = c.handler_factory()`（T9 前插件为空，此循环零迭代，前瞻兼容）。
  2. `document = Document(registry, confirmed_by=confirmed_by)`（构造签名按 C0 勘察；Document 第一参为 registry）。
  3. `bus = CommandBus(document, services.registry, services.kernel, handlers)`（参数序按 core/bus.py 实际签名）。
  4. **恰一次** `services.kernel.reset()`（构造完 bus 后、return 前）。
  5. `return LoadedDocument(document, bus)`。
- docstring：注明单例 kernel 跨文档复用、reset 责任在本工厂、多文档是阶段 1 方向。

### tests/test_layering.py（最小例外）
在现有守卫逻辑中将 `src/mycad/app.py` 单列白名单：允许其同时 import geom 与 core（组合根）；**仍禁** build123d/OCP/numpy 直接 import（该禁令对 app.py 照常生效）。改动最小化：只加例外判断，禁重构守卫。

### tests/app/test_composition.py
- `build_app(discoverers=[])`：`sorted(<8 id>)` 逐字 == ["feature.box","feature.cylinder","feature.extrude","feature.hole","feature.hole_pattern","feature.revolve","modify.boolean_cut","modify.fillet"]（UI 初稿 P0 表）。
- `dataclasses.fields(AppServices)` 名字元组 == ("registry","kernel","formats","plugins")。
- kernel/formats/plugins 均非 None；formats 经 resolve(".step") 能返回 provider（冒烟）；`services.plugins.discovered_plugins == ()`。
- `new_document(services)`：返回 LoadedDocument，document/bus 可用；`document.metadata == {"part_no":"","revision":"","material":"","source":"local"}`（T6 初值）；`document.commands == ()`。
- **跨文档隔离**：doc1 = new_document(services)；doc1.bus.execute("feature.box", {"size_x":10.0,"size_y":20.0,"size_z":30.0})；mass_properties solid_count==1；doc2 = new_document(services)；doc2 bus 的 kernel 状态：solid_count==0 且 volume==0.0（断言工厂 reset 生效；经 doc2.bus... 注意 mass_properties 在 kernel 上——LoadedDocument 暴露 bus，bus 持 kernel；测试可经 services.kernel.mass_properties() 直接断言，或经 doc2 执行后查询）。
- `feature.sweep` 执行 → pytest.raises(UnknownCommandError)（经 doc1.bus.execute("feature.sweep", {...})）。

### tests/app/test_builtin_execution.py（每命令 3 件套）
fixture：`services = build_app(discoverers=[])` + `doc = new_document(services)`（module/class 级，注意 kernel reset 语义——每测试新建 doc 即重置）。
8 命令各三测试（合法执行/校验失败/grammar 往返）：
- **合法执行**（体积/solid_count 断言）：
  - box：{size_x:10,size_y:20,size_z:30} → solid_count 1、volume==6000。
  - cylinder：{radius:40.0,height:8.0}（默认 center/mode）→ volume==math.pi*1600*8（容差 1e-6）。
  - extrude：{profile:{type:"circle",radius:5.0},distance:10.0} → solid_count 1、volume==math.pi*25*10（容差）。
  - revolve：{profile:{type:"rect",width:2.0,height:5.0,center:[10.0,0.0]},axis:"X"} → solid_count 1、volume>0（精确环体积可选，记公式则断言容差）。
  - hole：先 box{30,30,10}，再 hole{target_face:{surface:"plane",axis:"+Z",rank:0},position:{kind:"center"},diameter:5.0,depth:{kind:"through_all"}} → volume==9000-math.pi*6.25*10（容差）。
  - hole_pattern：法兰三步（cylinder r40 h8 + hole d20 + hole_pattern base d6 polar r25 count4）→ volume==math.pi*8*(1600-100-36)（容差 1e-6）。
  - fillet：box{10,10,10} 后 fillet{edges:[{parent_faces:[{surface:"plane",axis:"+Z"}]}],radius:1.0} → solid_count 1、volume<1000（去材料）。
  - boolean_cut：cylinder r10 h10 后 cut{tool:{type:"box",size_x:100,size_y:2,size_z:100,center:[0,0,0]}} → solid_count 1、volume<π·100·10（切掉一片）。
- **校验失败**（pytest.raises(ValidationError)）：box size_x=0.0；cylinder radius=-1.0；extrude 缺 distance；revolve angle_deg=0.0；hole diameter=0.0；hole_pattern pattern kind="linear"；fillet radius=0.0；boolean_cut 多余 mode 键（{tool:合法, mode:"cut"}→拒多余键）。
- **grammar 往返**：对每命令取**default 填充后的合法 params**（#round11-5：canonical to_cli 含默认键——先 validate_params 填充或手写全键），`text = to_cli(cid, params, services.registry)`，`parse_line(text, services.registry) == (cid, params)`（比较形态按 grammar 实际返回——先勘察 parse_line 返回是 tuple(cid, params) 还是对象，断言等价）。8 条：box/cylinder 全默认键；extrude profile 嵌套（扁平点键文法）；revolve axis "X"；hole 四键；hole_pattern 嵌套 base_hole.*；fillet edges 数组；cut tool 嵌套。
- `modify.fillet` 给线性 pattern 残留参数：{edges:合法, radius:1.0, pattern:{kind:"linear"}} → ValidationError（多余键）。

### tests/app/test_flange_qa.py（QA happy，进 evidence）
- **8 命令最小序列**：目标=单文档历史恰用全 8 个 id，终态体积==math.pi*8*(40**2-10**2-4*3**2)（容差 1e-6）且 solid_count==1。C0 第 6 项勘察 mode=new 语义后二选一（证据记录所用序列）：
  - **模式 A（mode=new 替换整体时）**：box(new) → extrude(new: circle profile) → revolve(new: rect profile) → cylinder(new: r40 h8 法兰毛坯) → fillet(选边) → boolean_cut(工具) → undo(2)（撤 fillet+cut）→ hole(中心孔 d20) → hole_pattern(4×d6)。总计 8 命令+2 undo，终态=法兰。
  - **模式 B（mode=new 新增 body 时）**：任意顺序执行 8 命令（法兰三命令放最后：cylinder(new)/hole/hole_pattern 收尾），随后 undo(5) 撤掉前 5 条，终态=法兰。
  - 序列细节（边选择器/工具参数/undo 数）由你按 C0 勘察微调，**唯一硬性验收**：8 id 全用、终态体积公式值、solid_count==1、全部经 bus.execute/undo（AppServices 路径）。
- 断言 `services.kernel.mass_properties()` volume 与公式差 <1e-6。
- **evidence 数据采集**（写进 §T7c）：所用 8 命令序列逐条（id+params 摘要）、终态体积实测值、solid_count、8 id 排序列表、每命令 help 文本行（`f"{spec.id}: {spec.summary_en}"` 形式）。

### evidence §T7c
追加：交付物、四门、mode=new 勘察结论、QA 序列与数据、deviations。

## 执行清单（按序，每步一回合）
- C0：八项前置读；确定 registry 枚举 API、FormatProviderRegistry 构造、mode=new 语义、parse_line 返回形态。
- C1：test_layering.py 加 app.py 例外（最小改动）→ 跑 pytest tests/test_layering.py 绿。
- C2：tests/app/__init__.py + test_composition.py 首批。
- C3：test_composition.py 完整 → 红（app.py 缺）。
- C4：app.py 首批（imports+AppServices+build_app）。
- C5：app.py 追加 new_document → test_composition 绿。
- C6：test_builtin_execution.py 首批（box/cylinder/extrude 三件套）。
- C7：追加 revolve/hole/hole_pattern。
- C8：追加 fillet/boolean_cut/失败面/grammar 往返。
- C9：test_flange_qa.py（按 C0 结论选模式 A/B，微调至绿）。
- C10：scoped 四门全绿。
- C11：evidence §T7c + DoneClaim。

## scoped 四门（C10，.venv/bin/python）
1. `.venv/bin/python -m pytest tests/app/ tests/test_layering.py tests/builtin_commands/ tests/plugins/ -q` → 全 passed。
2. `.venv/bin/python -m basedpyright src/mycad/app.py tests/app/ tests/test_layering.py` → 0/0/0。
3. `.venv/bin/python -m ruff check src/mycad/app.py tests/app/ tests/test_layering.py` → 全过。
4. `.venv/bin/python -m ruff format --check src/mycad/app.py tests/app/ tests/test_layering.py` → 全过。

## DoneClaim（最后一条消息，仅 JSON 代码块）
```json
{"claim":"DoneClaim","slice":"T7c","deliverables":["src/mycad/app.py","tests/test_layering.py(例外)","tests/app/test_composition.py","tests/app/test_builtin_execution.py","tests/app/test_flange_qa.py",".omo/evidence/task-7-phase0-mvp.md §T7c"],"four_gates":{"pytest":"<N passed>","basedpyright":"0/0/0","ruff_check":"...","ruff_format":"..."},"qa_sequence":"<所用 8 命令序列一句话>","mode_new_semantics":"<替换/新增>","deviations":["<每条一句>"],"notes":"<其他>"}
```
