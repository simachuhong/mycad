# U09 TRIM / EXTEND Crossing

依据 [AutoCAD 2025 TRIM](https://help.autodesk.com/cloudhelp/2025/ENU/AutoCAD-Core/files/GUID-B1A185EF-07C6-4C53-A76F-05ADE11F5C32.htm)，交叉窗口选择框内或与框相交的对象；边界交点按从第一角点出发的顺时针顺序确定选取位置。

1. 命令内 Crossing 收集两个对角点，显示预览，支持坐标输入、Esc、来源版本与锁定保护；复用围栏的精确有限交点和事务。
2. 顺时针处理框边交点，每个对象只处理一次；完整位于框内的有限对象使用曲线上明确点，退化或重合对象拒绝并整体回滚。
3. 覆盖 TRIM 快速/标准、EXTEND、目标框内与跨边、弧/多段线、混合来源、撤销与保存重开；参考软件未覆盖的复杂分支明确记录。
