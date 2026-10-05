# T5 清理任务：geom 特征层 lint + pyright 收零（机械清理，设计冻结）

你是 MyCAD 项目（/media/sima/Data/projects/MyCAD）的 geom 层清理代理。T5 语义已全部完成
（128/128 测试绿，篡改探针已闭环），只剩机械质量门收零。**禁止任何设计变更，只做类型收窄/lint/format。**

## 第一步（必做）

```bash
cat /media/sima/Data/projects/MyCAD/.omo/start-work/wave2-prompt-T5-cleanup.md  # 本文件
cat /media/sima/Data/projects/MyCAD/.omo/evidence/task-3-phase0-mvp.md  # §5：T3 closer 同款问题的修法参考
sed -n '1,80p' /media/sima/Data/projects/MyCAD/src/mycad/commands/grammar.py  # 参考实现：_as_dict/收窄模式
```

## 待修清单（当前实测状态）

1. **ruff B024**：src/mycad/geom/profiles.py:23 — `Profile(ABC) has no abstract members`。
   修法：给 Profile 加一个最小抽象成员（如 `@abstractmethod def area(self) -> float: ...`，
   CircleProfile/RectProfile 各实现之——数学正确即可），或去掉 ABC 直接用普通基类（选侵入更小者）。
2. **ruff format**：profiles.py 90 行区域需要重排——直接 `uv run ruff format src/mycad/geom profiles 相关文件`。
3. **basedpyright 69 errors**（全部 strict 模式）：
   - src/mycad/geom/_b123_features.py：55 个
   - src/mycad/geom/profiles.py：16 个（含 profiles.py:103:37 参数类型未知等）
   - tests/geom/：0（保持为零）
   错误类别：`Mapping[str, object]` 参数解析的 Unknown 渗漏——与 T3 closer 在 commands/grammar.py
   修过的问题同款。参考修法：isinstance 收窄 helper（_as_dict/_as_float/_as_str 模式）、
   cast 搭配类型守卫、参数入口统一 `Mapping[str, object]` 后立即收窄到具体类型。

## 硬性纪律（反停摆，机械遵守）

- 每回合恰一个小动作（一个文件的一小块）；单次文件写入 ≤100 行；用 edit 做小修改。
- 禁长篇设计推理——修法已在上面写死。
- 每修一批（~10 个错误）立即跑 scoped pyright 确认递减。
- **测试必须始终保持 128 passed**——修完每批跑 `uv run pytest tests/geom/ tests/test_layering.py -q`。

## 范围（白名单）

- 可改：src/mycad/geom/profiles.py、src/mycad/geom/_b123_features.py、
  src/mycad/geom/kernel.py（仅当类型签名需要）、tests/geom/test_features.py
  （**仅限类型注解/import 调整，禁止改任何断言与测试逻辑**）
- 禁止：改任何测试断言；git 操作；动其他目录；跑全量套件；改几何语义（任何输出值变化都是事故）

## 验证命令（scoped，全部必须绿）

```bash
uv run pytest tests/geom/ tests/test_layering.py -q          # 128 passed
uv run ruff check src/mycad/geom tests/geom                  # 0 error
uv run ruff format --check src/mycad/geom tests/geom         # 全 formatted
uv run basedpyright src/mycad/geom tests/geom                # 0 errors
```

## evidence 追加

在 .omo/evidence/task-5-phase0-mvp.md 末尾追加 `## 7. Cleanup session (lint + pyright zeroing)`
小节：记录四门命令结果、错误数递减轨迹（69→...→0）、采用的收窄模式清单。
（该小节追加前先 cat 现有文件确认无 §7。）

## 结尾必做

最终消息以 DoneClaim JSON 结尾（task/changed_files/tests/manual_qa/cleanup/risks）。
遇范围外阻塞报 BLOCKED: 原因并停止。
