# 二维 COPYMODE 设置计划

目标：依据 AutoCAD COPYMODE，允许通过命令栏设置 0（连续）或 1（单次）；设置属于应用偏好，跨文档及重启保留，不写入模型历史。

1. 先写真实命令栏测试，覆盖无效输入、两种模式、单次结束与连续放置、草稿重建及多文档切换。
2. 画布维护当前模式，命令栏接收并校验 COPYMODE 输入；独立二维默认 0，数值面板始终单次。
3. 在主窗口通过项目已有 QSettings 保存和读取偏好，文档切换时同步；独立测试组件默认不写用户配置。
4. 验证重开应用、输入法与 Esc、不修改文档及既有 COPY U/首点位移，运行受影响 UI 和代码质量 scoped 回归。

补充：COPY 选择完成、指定基点之前支持 Mode（Single/Multiple，修改持久偏好）及 Multiple（仅覆盖当前命令）；不可将参数选项误判为其他命令。先写窗口测试，再实现并验证取消、模式恢复与单次/连续放置。

参考 [AutoCAD COPYMODE](https://help.autodesk.com/cloudhelp/2022/ENU/AutoCAD-Core/files/GUID-BB3CED8E-4FA7-492A-8229-77A9021F67D7.htm)，不作为实机验收替代。

系统变量、持久化与 scoped 回归已实现；记录及限制见 [U09 进度](../../../.omo/evidence/ui-redesign/u09-progress.md)。

命令内 Mode/Multiple 已接入：Mode 修改持久偏好，Multiple 只覆盖当前命令；错误选项保留输入状态。真实参考产品及用户验收仍待执行。
