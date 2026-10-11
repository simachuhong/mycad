# Final F2 — 代码质量审查（Phase-0 MVP）

**结论：APPROVE（修复 2 项真实缺陷后）**

审查人：主会话（非只读——F2 按计划需要活体反向注入与修复权）。
基线：`feecf03` + 本轮 F2 修复。日期 2026-10-11。

---

## 摘要

F2 发现并修复了两处真实缺陷，其中第一处是**守卫失效**，性质严重：

1. **`test_no_type_ignore_or_pyright_ignore_sites` 自 T1 起一直判空**，从未检查过任何文件。
2. **`mycad.cli.__main__` ↔ `mycad.cli.session` 存在真实 import 环**，靠函数内延迟 import 绕开。

两处均已修复，修复后全量四门绿。

---

## 缺陷 1（严重）：零抑制守卫一直在空转

### 根因

`tests/test_layering.py` 原第 111–117 行：

```python
suffixes = ("py",)
...
if path.suffix not in suffixes:
    continue
```

`Path.suffix` 返回**带前导点**的 `".py"`，而白名单写的是不带点的 `"py"`。
因此 `".py" not in ("py",)` 恒为真，循环体对仓库里**每一个文件**都执行 `continue`。
`offenders` 永远是空列表，断言永远成立。实证：

```
$ uv run python -c "from pathlib import Path; print(repr(Path('x.py').suffix))"
'.py'
```

该守卫在 T1 落地、通过了全部 11 个任务波次的每一次全量跑，始终显示 PASS。

### 后果：4 处真实违规长期潜伏

修复 suffix 比较后守卫立即判红，暴露出 4 个计划明令禁止的抑制站点
（计划规定 `tests/typing/` 是全仓唯一合法位置）：

| 站点 | 内容 |
|---|---|
| `tests/core/test_geometry_types.py:28` | `box.xmin = 99.0  # type: ignore[misc]` |
| `tests/core/test_groups.py:31` | `group.name = "other"  # type: ignore[misc]` |
| `tests/core/test_groups.py:52` | `NamedGroup(..., faces=faces, edges=edges)  # type: ignore[arg-type]` |
| `tests/core/test_selectors.py:43` | `fs.surface = "cylinder"  # type: ignore[misc]` |

### 修复

**守卫本身**：改用 `REPO.rglob("*.py")` 直接按模式取文件，去掉出错的 suffix 比较；
补 `.venv` 排除；needle 改为分片拼接（`"# type" + ": ignore"`），使守卫文件自身不再
命中自己的检测——与 `tests/formats/test_guards.py` 既有约定一致。同时订正了模块
docstring 里「`tests/typing/` 是尚不存在的目录」这一已过期描述（该目录在 T6 已建立）。

**三处冻结赋值**（`test_geometry_types` / `test_groups` / `test_selectors`）：
直接给 frozen dataclass 字段赋值必然是静态错误，这正是原抑制注释的来由。改为经变量名
`setattr`（`field = "xmin"; setattr(box, field, 99.0)`），运行时行为逐字不变——仍然
`pytest.raises(dataclasses.FrozenInstanceError)`；用变量而非字面量是为了避开 ruff B010。

**`test_named_group_list_inputs_become_tuples`**：该用例靠 `# type: ignore[arg-type]`
传 list 去触发 `NamedGroup.__post_init__` 的 list→tuple 归一。核查全部构造点
（`src/mycad/core/persistence.py:204` 是 src 中唯一一处，它已显式构造 tuple；
`tests/` 中 9 处全部传 tuple），**没有任何调用方依赖该归一**。遂删除 `__post_init__`
与该用例，并订正类 docstring（原文声称「accept any iterable」，与类型标注矛盾）。
类型标注 `tuple[FaceSelector, ...]` 由此成为诚实的契约。

---

## 缺陷 2：CLI 层 import 环

### 根因

`src/mycad/cli/session.py:514` 在 `_cmd_help` 函数体内延迟 import：

```python
from mycad.cli.__main__ import HELP_TEXT
```

而 `__main__.py:21` 顶层 `from mycad.cli.session import CliSession`。延迟 import 让它在
运行时不炸，但依赖图上是真实的双向边。

### 修复

`HELP_TEXT` 的归属本就在 session 侧（它是 REPL 的 `help` 文本，`__main__` 只是转发）。
把常量移到 `session.py` 并加入其 `__all__`；`__main__.py` 改为
`from mycad.cli.session import HELP_TEXT, CliSession`——复用已有的那条 import 边，
不新增任何依赖。`__main__.__all__` 仍导出 `HELP_TEXT`，对外表面不变。

---

## 机器门：每个守卫一次活体反向注入

计划 F2 要求「分层守卫经活体反向注入证明有效（红后还原）」。探针脚本对真实源文件
写入违规内容 → 跑守卫 → 必须红 → 还原 → 必须绿；任一环节不成立即判 FAIL。

```
[PASS] src-backend-import       注入 import numpy 到 src/mycad/core/document.py
                                -> tests/test_layering.py::test_src_has_no_backend_imports
[PASS] tests-backend-import     注入 import build123d 到 tests/core/test_groups.py
                                -> tests/test_layering.py::test_tests_import_backends_only_in_geom_scope
[PASS] type-suppression         注入抑制注释到 src/mycad/core/groups.py
                                -> tests/test_layering.py::test_no_type_ignore_or_pyright_ignore_sites
[PASS] second-composition-root  注入 mycad.geom import 到 src/mycad/cli/session.py
                                -> tests/test_layering.py::test_composition_root_is_the_geom_core_bridge
[PASS] forbidden-import-root    注入 import requests 到 src/mycad/cli/session.py
                                -> tests/test_scope_audit.py::test_no_forbidden_imports
[PASS] commercial-format        注入 "part.sldprt" 到 src/mycad/formats/registry.py
                                -> tests/test_scope_audit.py::test_no_out_of_scope_code

all 6 reverse injections confirmed: red on violation, green after revert
```

注入后 `git status --porcelain` 仅含本轮有意修改的文件，无残留。

**关键点**：`type-suppression` 这一条在本次修复**之前**会是 FAIL（注入后守卫仍绿）。
它现在能判红，正是缺陷 1 已被真正修掉的证据，而非形式上的通过。

---

## 其余 F2 条目

### 零 `# type: ignore` / 零 `# pyright: ignore`

修复后 `tests/typing/` 外 0 处。由现在真正生效的守卫持续强制。
`tests/typing/expect_errors.py` 内 1 处，属白名单内的 expect-error 语料，合规。

### 零 `Any` 逃逸

`src/` 内 `Any` 仅 2 处，均为 JSON 边界的合法用法，不是绕过类型检查的逃逸：

- `src/mycad/builtin_commands/defs.py:30` `COMMAND_SCHEMA_DEFS: Mapping[str, Any]` —— JSON Schema 文档树
- `src/mycad/core/migrations/__init__.py:27,39` `dict[str, Any]` —— 存档迁移函数签名，作用对象是任意深度的 JSON

其余跨类型边界一律走 `cast(...)`（显式、可 grep、不抑制诊断）。

### 零空 except

`src/` 内 2 处 `except ...: pass`，均非裸 except，均有正当理由，判过：

- `src/mycad/cli/session.py:26` `except ImportError: pass` —— 可选 `readline`，标准的可选依赖惯用法，带注释
- `src/mycad/core/persistence.py:132` `except OSError: pass` —— 位于外层 `except BaseException: ... raise` 内的临时文件尽力清理；吞掉清理失败是对的，否则会掩盖已在 re-raise 的原始异常

两处都不丢数据，都不吞掉需要用户感知的错误。

### 模块依赖无环

对 `src/mycad` 全部 52 个模块做 AST import 图 + DFS 环检测（含 `TYPE_CHECKING` 块内的
边——只有类型检查器看得见的环也是设计上的环）：

- 修复前：1 个环（`cli.__main__` ↔ `cli.session`）
- 修复后：**0 个环**

### 公共 API docstring

扫描 `src/mycad` 全部模块级公共类/函数与公共方法：

- 修复前缺 8 处。补齐 `cli/plans.py::ValidatedPlan`、`core/handlers.py::BuiltinModelingHandler.handle`。
- 剩余 6 处全部位于 `src/mycad/geom/_b123_ops.py`——模块名前导下划线，是 `geom` 的内部
  实现细节，不属公共 API 表面。判为可接受，不补。

---

## 四门（全量，修复后）

```
$ uv run ruff format .      → 163 files left unchanged
$ uv run ruff check .       → All checks passed!
$ uv run basedpyright       → 0 errors, 0 warnings, 0 notes
$ uv run pytest -q          → 793 passed, 1 skipped in 82.71s
```

无任何 per-file 豁免、无 `noqa` 新增（`session.py` 内既有的 2 处 `noqa` 是 T7c/T10 既有的
B009/F401，带说明注释）。

用例数 794 → 793：删除了 `test_named_group_list_inputs_become_tuples`（见缺陷 1 修复）。
跳过的 1 条是 `tests/test_acceptance_flange.py:286` PySide6 外壳，按计划属阶段 1。

全新环境下的 `uv sync --frozen` + 四门复跑结果见 `final-3-phase0-mvp.md`（F3 在干净克隆里
执行，两项共用同一套环境证据）。

---

## 遗留风险

- **同类 bug 的面**：本次只在仓库里找到 1 处 `path.suffix` 与无点字面量比较
  （`rg '\.suffix' tests/ src/ scripts/` 共 4 处，其余 3 处均正确带点）。但「守卫写了却
  一直空转」这个失败模式本身无人看守——没有任何元测试断言各守卫**扫到了非零数量的文件**。
  建议阶段 1 给每个遍历型守卫加一条 `assert scanned > 0`。
- `_b123_ops.py` 的 6 个无 docstring 函数虽属内部，但它们是 geom 适配层的参数解析核心，
  阶段 1 若对外开放需补齐。
