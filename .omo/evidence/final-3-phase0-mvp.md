# Final F3 — 真实手工 QA（Phase-0 MVP）

**结论：APPROVE，附一项已知缺口（Windows 就绪未实测）**

全部步骤为真实执行，非日志转述。环境：干净克隆 `/tmp/mycad-clean`
（`git clone` 自主仓，基线 `feecf03` + F2 修复），Ubuntu，CPython 3.12.3。
日期 2026-10-11。

---

## 1. 从零走 README 快速开始

### `uv sync --frozen`（全新 venv，同时作为 F2 的全新环境证据）

```
$ git clone <repo> /tmp/mycad-clean && cd /tmp/mycad-clean
$ uv sync --frozen
Checked 61 packages
$ du -sh .venv   → 905M
```

四门在该全新环境下复跑：

```
uv run ruff format --check .  → 163 files already formatted
uv run ruff check .           → All checks passed!
uv run basedpyright           → 0 errors, 0 warnings, 0 notes
uv run pytest -q              → 793 passed, 1 skipped in 50.79s
```

（793 为 F2 修复后、`commands` 修复前的计数；主仓当前为 794。）

### README 的三条命令，逐字执行

```
$ uv run mycad run examples/flange_script.txt
new document
part_no=FLANGE-DEMO-001
revision=A
material=Q235
source=example
flange.step
flange.stl
flange.mc.json
{"commands": [{"id": "feature.cylinder", ...}, {"id": "feature.hole", ...},
              {"id": "feature.hole_pattern", ...}]}
exit=0

$ uv run mycad run --json examples/flange_plan.json
examples/flange_plan.step
examples/flange_plan.stl
examples/flange_plan.mc.json
exit=0
```

六个产物齐全，两条路径的 STEP 与 STL **字节数完全相同**
（STEP 24507 B，STL 152084 B）。STEP 文件内容在第 4 行有差异，为头部文件名/时间戳，
非几何差异——由下节回读证实。

`git status --porcelain -uall` 不含任何 flange 行：T11 补的六条 `.gitignore` 规则在
真实运行产物上生效。

---

## 2. STEP 回读校验

用 `tests/helpers/step_roundtrip.py` 同款 `build123d.import_step` 把两个 STEP 读回来：

```
README formula volume  = 36794.333158843656     (math.pi*8*(40**2-10**2-4*3**2))
golden expected_volume = 36794.3331588437       (tests/golden/flange_golden.json groups.A)

=== flange.step ===                  === examples/flange_plan.step ===
  solids    = 1                        solids    = 1
  volume    = 36794.3331588            volume    = 36794.3331588
  delta     = 1.419e-09 mm^3           delta     = 1.419e-09 mm^3
  bbox size = (80.0000, 80.0000, 8.0000)   同左
  faces     = 8                        faces     = 8
  cyl faces = 6                        cyl faces = 6
```

两条路径几何完全等价，与闭式真值吻合到 1.4e-9 mm³。6 个柱面 = 外圆 + 中心孔 + 4 个
螺栓孔，与 golden 的 `cylindrical_faces: 6` 一致。golden 表自身与其 `_formula` 相符
（差 < 1e-9），未发生「从实现输出反向记录」。

---

## 3. 交互式 REPL 全流程

真实 `uv run mycad` 会话，走 new → 建模 → undo → redo → meta → save → export →
new → open → export → quit：

```
new                              → new document
cylinder radius=40 ...           
hole target_face... diameter=20  
history                          → 0: feature.cylinder ...
                                   1: feature.hole ...
undo                             
history                          → 0: feature.cylinder ...          （只剩 1 条）
redo                             
history                          → 0: feature.cylinder ...
                                   1: feature.hole ...              （恢复 2 条）
meta part_no=QA-REPL-001         → part_no=QA-REPL-001
save /tmp/f3qa/qa.mc.json        → /tmp/f3qa/qa.mc.json
export /tmp/f3qa/qa.step         → /tmp/f3qa/qa.step
new                              → new document
history                          → （空，正确）
open /tmp/f3qa/qa.mc.json        → opened /tmp/f3qa/qa.mc.json
history                          → 2 条命令完整复现，confirmed_by=cli-local 保留
export /tmp/f3qa/reopened.stl    → /tmp/f3qa/reopened.stl
quit                             → exit=0
```

存档往返无损：重开后历史逐条一致，可继续导出。

---

## 4. 故意制造批事务失败：回滚与退出码

脚本在 `begin-batch`/`end-batch` 内放一条合法 `hole` 和一条非法 `cylinder radius=-5`：

```
$ uv run mycad run /tmp/f3qa/batch_fail.txt
batch failed at step 1 (feature.cylinder): radius: value -5 violates exclusiveMinimum 0.0
rolled back: 1
exit=1
```

**回滚不仅记在账上，几何上也无痕**——同一批次在 REPL 里复跑后导出：

```
history  → 0: feature.cylinder radius=40 ...     （批内的 hole 已消失）
export /tmp/f3qa/after_rollback.step
回读：volume = 40212.3860  expected = pi*8*40^2 = 40212.3860
      cyl faces = 1                              （只剩外圆，无孔）
```

### 退出码契约三态实测

| 场景 | 实测退出码 | 期望 |
|---|---|---|
| `mycad commands`（正常） | 0 | 0 |
| 批事务建模失败 | 1 | 1 |
| `validate` 遇未知命令动词 | 1 | 1 |
| `mycad bogus-subcommand` | 2 | 2 |
| `mycad run <不存在的文件>` | 2 | 2 |
| `mycad help extra-arg` | 2 | 2 |

---

## 5. 其余 CLI 子命令

```
$ uv run mycad validate examples/flange_plan.json   → valid: plan 3 step(s)    exit=0
$ uv run mycad validate examples/flange_script.txt  → valid: script 3 step(s)  exit=0
$ uv run mycad commands                             → 8 行制表符三列            exit=0
$ uv run mycad plugins                              → （干净环境下空）          exit=0
```

### 本节发现一处真实缺陷（已修）

真实安装示例插件后：

```
$ uv pip install -e plugins_examples/mycad_plugin_demo
$ uv run mycad plugins
loaded: mycad-plugin-demo v0.1.0 api=1.0 commands=1 formats=1
$ uv run mycad commands | wc -l
8                                    ← 应为 9
$ printf 'new\nping\nquit\n' | uv run mycad
0: demo.ping ping  [confirmed_by=cli-local]    ← REPL 能执行
```

三个发现面自相矛盾：`plugins` 说插件贡献了 1 条命令，REPL 能执行它，而 `commands`
永远看不见它。根因是 `src/mycad/cli/__main__.py` 的 `commands` 分支写成
`build_app(discoverers=[])`，把**测试用的隔离手段写进了生产代码**。

计划第 444 行对此有明文：「无插件时恰好 8 行」，隔离应「在禁用 entry-point 发现的
进程/monkeypatch 环境中运行」，且「另设一例装了 demo 插件的环境断言为 **9 行**且多出
`demo.ping`」。后半条此前没有任何测试覆盖，所以缺陷在全量四门下一直不可见。

已修（commit `688d001`）：生产代码改回 `build_app()`；两条计数测试自己 monkeypatch
`EntryPointDiscoverer.discover`；新增的 9 行用例**经 `main()` 驱动**而非直调
`CliSession`——直调覆盖不到出错的那行接线。篡改探针确认：把生产代码改回
`discoverers=[]` 后新用例判红，还原后转绿。

插件卸载后 `commands` 回到 8 行、`plugins` 回到空输出，无残留。

---

## 6. 国内镜像指引演练

README 的镜像小节此前从未被实测过。真实执行（独立克隆 `/tmp/mycad-mirror`）：

```
$ export UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
$ uv sync
Resolved 63 packages in 47.94s
...
real    9m58.005s
```

镜像环境可用：法兰两条路径 exit=0，`ruff check` 通过，`basedpyright` 0/0/0，
`pytest` 793 passed 1 skipped。

### 本节发现一处文档隐患（已修）

```
$ git status --porcelain uv.lock
 M uv.lock
$ git diff --stat uv.lock
 uv.lock | 1126 ++++++------  (563 insertions, 563 deletions)
```

按 README 原指引操作会把 `uv.lock` 中**全部 563 个包**的 `source` 与下载 URL 从
`pypi.org` / `files.pythonhosted.org` 改写为清华源（sha256 不变，完整性不受影响）。
原文没有任何提示。若贡献者误提交这份改写，CI 三个 runner 以 `--frozen` 安装，会被
一并钉到国内镜像——对 `windows-latest` 尤其是不可接受的依赖源变更。

已在 README 镜像小节补一段警示：说明该改写、要求不要提交、给出
`git checkout uv.lock` 的还原动作。

---

## 7. CI 与多平台：已知缺口

**本仓库没有配置任何 git remote**（`git remote -v` 输出为空），因此：

- **无法提供 CI job 链接**，三个 runner（`ubuntu-22.04` / `ubuntu-24.04` /
  `windows-latest`）**一次都没有真实跑过**。
- **Windows 就绪未实测**。本结论**不主张**任何多平台验证。

可静态核查、因而已核查的部分：

- `.github/workflows/ci.yml` 的 matrix 确为三个 runner，步骤为
  `uv sync --frozen` + 四门，与本地执行的命令逐字一致。
- `uv.lock` 为 `cadquery-ocp-novtk` 与 `build123d` 均记录了 `win_amd64.whl`，
  依赖层面 Windows 可安装。
- 跨平台路径处理由 `tests/test_scope_audit.py::test_src_uses_pathlib_not_hardcoded_separators`
  机器强制。

这三点共同支持「Windows **就绪**」，但都不能替代一次真实的 Windows 运行。
推送到远端并让 CI 跑一轮是关闭该缺口的唯一途径，属阶段 0 交付后的第一件事。

---

## 遗留风险

- **Windows / 多平台零实测**（上节），阶段 0 验收范围内无法关闭。
- 镜像路径首次同步耗时近 10 分钟且 `uv.lock` 会被改写；README 现已警示，但没有机器
  守卫阻止误提交被改写的 lock。建议阶段 1 加一条 CI 检查：`uv.lock` 内不得出现
  `pypi.org` 以外的 registry。
- `uv run mycad plugins` 在无插件时静默输出空字符串。契约上 exit 0 正确，但对用户而言
  与命令失败难以区分；非缺陷，记为阶段 1 的可用性改进点。
