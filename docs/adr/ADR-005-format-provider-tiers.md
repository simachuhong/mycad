# ADR-005 格式提供方分级

Status: Accepted 2026-09-17

## Context

CAD 格式互操作横跨免费开源与商业授权两界，必须在第一天就把授权墙隔离在 Apache-2.0 核心之外（NF-05 开源合规；技术路线 §9 开源与第三方：不引入 GPL/AGPL 作为主许可证、第三方归属随依赖补充）。OCCT 7.8 的 DE_Wrapper 已给出经验证的 provider 注册表模型（FormatName × VendorName 分组、统一 Parameters、shape 或 XCAF document 两级目标，E10）——MyCAD 的 FormatProvider 缝直接对齐该样板，避免自发明注册表语义。免费格式的产品化按价值排序推进；商业内核格式（JT/Parasolid/ACIS/SolidWorks/NX/CATIA）在 OCCT 中本就是商业附加组件（E10 与 E5 互证），只能经外部持证插件进入。DWG 无免费合规写路径（R11），是合规雷区。

## Decision

1. **注册表模型**：FormatProvider 注册表对齐 OCCT 7.8 DE_Wrapper 的 name×vendor provider 模型（E10），provider 声明 can_read/can_write 与目标（`target="shape"`；"xcaf" 仅为阶段 1 装配导入预留字面量）。另加 `priority` 整数：默认 100；同一扩展名存在多个 provider 时取最小值者胜出；priority 相同且扩展名重叠的两个 provider 注册时抛 `ProviderConflictError(extension, provider1, provider2)`——冲突必须显式暴露，不做隐式覆盖。
2. **导入三级枚举**：DUMB_SOLID（哑实体）/ ASSEMBLY_WITH_ATTRS（带装配属性：颜色、名称、材料）/ EDITABLE_FEATURES（可编辑特征）——任何外部格式永远到不了第三级：导入件以哑实体或装配属性形态进入文档，可编辑性只能由 MyCAD 自身的命令历史产生。
3. **免费序列（产品化顺序）**：STEP AP242 / STL / BREP → IGES / glTF / OBJ → 3MF（lib3mf）/ DXF（ezdxf）。阶段 0 的产品化范围：STEP 只写产品化；STEP 读仅是测试辅助路径（`tests/helpers/`，用于导出件往返断言），F-DOC-03 的产品化导入在阶段 1；STL 只写；BREP/IGES/glTF/OBJ/3MF/DXF 按上列顺序在后续阶段推进。阶段 1 读路径的线程安全纪律：每个 STEP reader 持有独立的参数实例（对齐 OCCT DE_Wrapper 的每-reader 独立 DE 参数纪律，E10）。
4. **商业墙**：JT / Parasolid（x_t）/ ACIS（sat）/ sldprt / NX / CATIA 仅经外部持证第三方插件（E5：ODA 会员制无席位费 vs CAD Exchanger 按席位季度计费，两者的授权均不可随 Apache 核心再分发，集成商/最终用户持证自装）。核心不为商业格式承诺任何时间表。
5. **DWG 不碰**：无免费合规写路径（R11），不引入逆向库；ODA 转换器（若用户需要）属用户自装的外部工具，不进核心依赖。

## Consequences

- 正面：授权风险被结构性隔离（核心永远只含 OCCT 开源 DataExchange 与自带免费依赖的格式）；DE_Wrapper 对齐使注册表语义有上游经验背书；priority + 冲突显式报错使多 provider 共存可预测。
- 负面/边界：外部格式导入件不可编辑是永久性限制（用户预期管理要在文档中明确）；STEP 读的产品化（F-DOC-03，含 `document.import_step` 历史节点形态，见 ADR-002）推迟到阶段 1，阶段 0 的 STEP 读只存在于测试辅助路径；商业格式须用户自行持证装插件。
- 3MF/DXF 无新原生依赖：lib3mf 与 ezdxf 由 build123d 依赖树自带（E10；aarch64 自动切 py-lib3mf）。

## References

- docs/需求分析书.md F-DOC-03（STEP 导入）、NF-05（开源合规）
- docs/技术路线.md §9 开源与第三方（Apache-2.0、NOTICE 归属、不引入 GPL/AGPL 主许可证）
- 研究台账 A17（格式注册表与免费序列）、E5（ODA vs CAD Exchanger 授权模式）、E10（OCCT 7.8 DE_Wrapper provider 模型与免费/商业格式清单）、R7（商业格式无免费读路径）、R11（DWG 合规雷区）
- .omo/plans/phase0-mvp.md C8（FormatProvider 缝）、T4（本 ADR 指令）、T7/T8（provider 实现）
- ADR-002（存档 schema 与导入型历史节点的阶段 1 演进口）、ADR-003（mycad.formats entry 组）
