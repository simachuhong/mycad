# T9a 任务书：插件 manifest 解析 + entry-point 发现（纯进程内夹具）

你是 MyCAD 项目 T9a 片的执行代理。**第一动作：`cat` 本文件已由点火完成。按 §5 清单机械执行，禁重新设计。**

## 0. 反停摆五纪律（违反=任务失败）

1. 禁写清单文件以外的任何文件；2. 单文件一次写 ≤100 行（cat > 首块 / cat >> 追加续块）；3. 每回合只做一个小动作；4. 禁长推理——设计已全部钉死，照抄执行；5. 遇阻即止：输出 `BLOCKED: <原因>` 并结束回合。

## 1. 白名单（仅允许创建/修改）

- 新建 `src/mycad/plugins/manifest.py`、`src/mycad/plugins/discovery.py`
- 修改 `src/mycad/plugins/__init__.py`（补导出 EntryPointDiscoverer）
- 新建 `tests/fixtures/plugins/`（七棵夹具树 + 各树 pyproject.toml，结构见 §4）
- 新建 `tests/plugins/conftest.py`（sys.path 夹具注入）
- 新建 `tests/plugins/test_manifest.py`、`tests/plugins/test_discovery.py`
- 修改 `tests/plugins/test_agent.py`（公开面锁更新，§3）
- 追加 `.omo/evidence/task-9-phase0-mvp.md` §T9a（文件不存在则新建，SPDX 无要求，用与其他 task-N evidence 一致的纯 markdown）
- **禁改**：types.py/manager.py/commands//core//formats//geom//app.py/pyproject.toml/uv.lock；禁 git 操作；禁对任何夹具调 pip。

## 2. 上下文与依赖面（勿重复勘察，直接使用）

- 计划原文：`sed -n '400,428p' .omo/plans/phase0-mvp.md`（T9 全规格）。A0 必读。
- **T7b 契约（禁改）**：`mycad.plugins.types` 提供 CommandContribution(spec,handler_factory) frozen / PluginDiscoverer Protocol（唯一方法 discover()->Sequence[DiscoveredPlugin]）/ DiscoveredPlugin frozen 恰六字段（distribution_name:str, entrypoint:tuple[str,...], manifest:PluginManifest|None, commands:tuple[CommandContribution,...]=(), formats:tuple[FormatProvider,...]=(), warnings:tuple[str,...]=()）/ PluginManifest frozen 恰五字段（id,version,api_version,permissions=(),homepage=""）/ CURRENT_API_VERSION="1.0"+CURRENT_API_MAJOR=1 / WARNING_REASON 六码 Literal（missing-manifest/manifest-error/incompatible-api/command-conflict/provider-conflict/load-error）+WARNING_REASONS frozenset。
- **六码字面量守卫（AST，已有测试）**：六码字符串字面量只允许出现在 `src/mycad/plugins/types.py` 与 `tests/plugins/` 测试文件；manifest.py/discovery.py 中的码必须经 `get_args(WARNING_REASON)` 派生（T7b manager.py `_MISSING_MANIFEST = get_args(WARNING_REASON)[0]` 同模式）。**注意 get_args 源序**：missing-manifest 是 Literal 首位。
- **运行时事实（py3.12.3 实测）**：`EntryPoint(name, value, group)` 仅三位置参构造；`.dist` 不可注入（手造 EP 恒 None）；`.module`/`.attr` 从 value="pkg.mod:attr" 派生；真实 entry_points() 返回的 EP 带 .dist（Distribution，`.metadata["Name"]` 取名）。当前环境两组零 EP。
- FormatProvider 八字段必填（formats/base.py）；CommandSpec frozen（commands/spec.py）；registry.register 同 (id,version) 重复→CommandConflictError——T9a 均只做类型引用，不注册。
- pytest 用 `.venv/bin/python -m pytest`；basedpyright/ruff 用 `.venv/bin/`。

## 3. 钉死设计（逐条照抄）

### 3.1 `src/mycad/plugins/manifest.py`

- 模块 docstring 注明：PluginManifest/常量唯一权威在 types.py（#round9-4/5），本模块零修改只 import。
- `def resolve_manifest(module: object) -> tuple[PluginManifest | None, str | None]`：
  - 取 `getattr(module, "manifest", None)`；None→`(None, "missing-manifest 码")`。
  - 三形态归一：dict → 校验后构造；零参 callable → 调用一次，返回值再归一（返回 dict/PluginManifest 实例；否则 manifest-error）；PluginManifest 实例 → 直接用；其他类型 → manifest-error。
  - dict 校验：五键 id/version/api_version 必填 str 且非空；多余键或缺失键→manifest-error；permissions 可选 list[str]/tuple[str]→tuple；homepage 可选 str 默认 ""；id 不匹配 `^[a-z0-9_.-]+$`→manifest-error；类型错→manifest-error。
  - api 门：`api_version` 取 `int(str.split(".", 1)[0])`；ValueError（"v1"/"abc"）或 ≠ CURRENT_API_MAJOR → **(None, incompatible-api 码)**（此时其余字段合法性不再判——先解析 api_version 再判，规格如此）。
  - 全部 reason 经 get_args(WARNING_REASON) 常量派生，禁裸字符串。
- `__all__ = ["resolve_manifest"]`。

### 3.2 `src/mycad/plugins/discovery.py`

- `class EntryPointDiscoverer:` 构造 `__init__(self, groups: tuple[str, ...] = ("mycad.commands", "mycad.formats")) -> None` 存 tuple；实现 PluginDiscoverer Protocol（结构满足即可，不显式继承）。
- `def discover(self) -> tuple[DiscoveredPlugin, ...]`：
  1. 对每个 group 调 `importlib.metadata.entry_points(group=g)`（kwargs 形式，py3.10+）。
  2. **distribution 名**：模块私有 `_distribution_name(ep) -> str`——`ep.dist` 非 None 且 `ep.dist.metadata["Name"]` 非空→用之；否则 fallback `ep.module`。docstring 注明手造 EP 无 dist 的 fallback 语义（evidence 记 deviation）。
  3. **manifest memoize**：按 module 对象 memoize `resolve_manifest` 结果（同模块多 EP 只解析一次；callable 形态只调一次）。
  4. **entry 契约求值**（组隔离）：对每个 EP：`ep.load()` 得 attr 对象；必须为零参 callable（非 callable→该组跳过+load-error）；调用恰一次；返回必须 list（非 list→跳过+load-error）；逐元素校验（mycad.commands 组元素 isinstance CommandContribution；mycad.formats 组元素 isinstance FormatProvider；任一元素类型错→**该组整体跳过**+load-error）；callable/调用抛异常→该组跳过+load-error。**任一组失败不影响另一组**。
  5. **同 distribution 合并**：一个 DiscoveredPlugin（commands/formats 分列合并、entrypoint 去重排序 `<group>:<module>:<attr>`、warnings 合并去重保持六码序）。
  6. **manifest 失败的插件**：commands/formats 强制 ()（组求值跳过）+warnings 携 manifest 码。
  7. 按 distribution_name 排序返回 tuple。
- 修改 `plugins/__init__.py`：再导出 += `EntryPointDiscoverer`（从 .discovery import），`__all__` 同步。
- **tests/plugins/test_agent.py 锁更新**：PLUGINS_PUBLIC_NAMES += "EntryPointDiscoverer"（恰七名）；PLUGINS_SUBMODULE_ARTIFACTS 改 `{"types", "manager", "discovery", "manifest", "loader"}`（预列 T9b loader，免疫 import 顺序非确定性）；测试函数名 six→seven 相应更新。断言逻辑不变（names - ARTIFACTS == PUBLIC）。

### 3.3 夹具七棵树（tests/fixtures/plugins/）

每棵：`<pkg>/pyproject.toml`（仅文档价值：[project] name/version + [project.entry-points."mycad.commands"]/["mycad.formats"] 声明）+ 模块源码。**目录即包名**，模块顶层放夹具代码。七棵：

1. `mycad_plugin_manifest_dict/`：`__init__.py` 定义 `manifest = {"id": "manifest-dict", "version": "1.0.0", "api_version": "1.0"}` + `def commands() -> list[CommandContribution]: return []`（空 list 合法零注册）。
2. `mycad_plugin_manifest_callable/`：`manifest = _make_manifest`（零参 callable 返 dict，模块级计数器 `CALL_COUNT` 每次 +1，证 memoize 只调一次）+ commands 返单条 CommandContribution（自造 demo.spec.1：id="demo.spec.1" version=1 summary_en="S1" label_zh="甲" cli=CliSyntax(("s1",)) params_schema={"type":"object","properties":{},"required":[],"additionalProperties":false} handler_factory=None）+ formats 同理返单条自造 provider（.ft1 扩展名，八字段齐全）。
3. `mycad_plugin_future/`：manifest api_version="9.9"。
4. `mycad_plugin_bad/`：子模块 missing_attr（无 manifest 属性，仅 commands 空函数）/bad_missing（manifest dict 缺 version）/bad_extra（多 unknown 键）/bad_types（version=1.0 非 str）/bad_id（id="Bad Id"）。
5. `mycad_plugin_matrix/`：子模块 api_1_0（"1.0"）/api_1_5（"1.5"）/api_2_0（"2.0"）/api_v1（"v1"）/api_abc（"abc"），各带 manifest+空 commands。
6. `mycad_plugin_conflict/`：commands 返 CommandContribution(id="feature.box" 撞内置，spec 自造同名)/formats 返 .txt priority=100 provider（T9b 用；本片仅放置）。
7. `mycad_plugin_formats/`：子模块 empty_factory（formats 返 []）/raise_factory（formats raise RuntimeError("boom")）/single（formats 返单元素）。

夹具 spec/provider 构造 helper 放各树模块内（禁跨树 import）。conftest.py：`sys.path.insert(0, str(Path(__file__).parent / "fixtures" / "plugins"))` + fixture yield 后 remove（幂等）。

### 3.4 测试（test_manifest.py + test_discovery.py）

- **test_manifest.py**（≥12 例）：三形态归一（dict/callable/实例）；missing→missing-manifest；bad_missing/bad_extra/bad_types/bad_id→manifest-error；api 矩阵 "1.0"/"1.5"→(manifest, None)，"2.0"/"v1"/"abc"→(None, incompatible-api)；id 正则合法值通过；permissions tuple 化+homepage 默认。reason 断言用 get_args(WARNING_REASON) 常量（禁裸码字符串——测试文件允许，但统一风格）。
- **test_discovery.py**（≥14 例）：monkeypatch.setattr(importlib.metadata, "entry_points", fake)（fake 按 group 返回手造 EntryPoint 列表）；①manifest_dict 发现（distribution_name=="mycad_plugin_manifest_dict" 回退 module 名、commands 空、零 warning）；②callable 树合并（两组同模块→一个 DiscoveredPlugin、entrypoint 去重排序、CALL_COUNT==1）；③future→incompatible-api+commands()==()；④bad 各子模块→manifest-error/missing-manifest；⑤matrix 五例参数化；⑥formats empty/raise/single→空注册/load-error（组隔离：raise_factory 若同插件有 commands 组则 commands 不受影响）/单元素；⑦非 callable attr（模块属性放非函数对象）→load-error；⑧返回非 list→load-error；⑨元素类型错→该组整体跳过；⑩排序确定性（两次 discover 相等，断言 (distribution_name,[spec.id,...]) 形态避开闭包身份）；⑪真实环境（不 monkeypatch）两组零 EP→discover()==()（当前环境干净）；⑫discovered_plugins 经 PluginManager(plugins).loaded() 排除 manifest None 者。
- 夹具模块 import 用 importlib.import_module（conftest 已注入 sys.path）。

## 4. 通用纪律

- SPDX 两行头（Apache-2.0+"MyCAD contributors"），参照 src/mycad/plugins/types.py；新文件 basedpyright strict 零 ignore；ruff（E/F/W/I/B/UP/C4）全过。
- 测试 docstring 禁出现会被守卫扫描的字面量。
- TDD 允许（先红后绿）但每文件落盘即合规。

## 5. 执行清单（逐步机械执行，每步一回合）

- A0：`sed -n '400,428p' .omo/plans/phase0-mvp.md` 读规格；`cat src/mycad/plugins/types.py src/mycad/plugins/manager.py` 读契约；`cat tests/plugins/test_agent.py` 读锁。
- A1：写 manifest.py（≤100 行一块完成）。
- A2：写 tests/plugins/conftest.py + test_manifest.py 首块（测试骨架+前 6 例）。
- A3：test_manifest.py 追加后 6+ 例；`.venv/bin/python -m pytest tests/plugins/test_manifest.py -q` 红→绿（manifest.py 修至绿）。
- A4：写 discovery.py（两块：_distribution_name+组求值 / 合并+排序+discover）。
- A5：写夹具树 1-3（manifest_dict/callable/future）。
- A6：写夹具树 4-5（bad/matrix）。
- A7：写夹具树 6-7（conflict/formats）。
- A8：写 test_discovery.py 首块（fake EP helper+发现/合并/memoize 例）；跑红。
- A9：test_discovery.py 追加剩余例（异常矩阵/排序/真实环境）；跑绿。
- A10：改 plugins/__init__.py + test_agent.py 锁；`pytest tests/plugins/ -q` 全绿。
- A11：scoped 四门：`.venv/bin/python -m pytest tests/plugins/ -q` + `.venv/bin/basedpyright src/mycad/plugins/ tests/plugins/` + `.venv/bin/ruff check src/mycad/plugins/ tests/plugins/ tests/fixtures/` + `.venv/bin/ruff format --check` 同路径（fixtures 的 pyproject.toml 不归 ruff 管，仅 .py）。**注意**：basedpyright 命令对目录递归，tests/fixtures/plugins 的 .py 会被扫到——夹具代码也须 strict 合规（import 的 mycad 类型在 venv 可解析，sys.path 注入不影响静态检查）。
- A12：追加 evidence §T9a（交付物清单/四门结果/设计偏离：_distribution_name fallback/get_args 码派生/夹具不进 wheel 说明）。
- A13：输出 DoneClaim JSON（终消息）：
```json
{"task": "T9a", "status": "DONE", "deliverables": ["<逐文件路径+行数>"], "gates": {"pytest": "<N passed>", "pyright": "0/0/0", "ruff": "pass"}, "deviations": ["<逐条>"], "notes": "<备忘>"}
```
