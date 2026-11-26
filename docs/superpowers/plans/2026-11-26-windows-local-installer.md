# Windows Local Installer Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement task-by-task.

**Goal:** 提供可在 Windows x64 本机构建和测试的 MyCAD Setup.exe，以及日志和检查清单。

**Architecture:** PyInstaller 收集目录产物；Inno Setup 安装到当前用户目录。
GUI 和控制台辅助程序共享依赖，源码 CLI 行为保持兼容。

**Tech Stack:** Python 3.12、PowerShell 5.1+、PyInstaller、Inno Setup 6。

**Spec:** docs/superpowers/specs/2026-11-26-windows-desktop-package-design.md

## Global Constraints

- 用户已确认准备本机构建脚本、安装日志和清单；本会话直接实施，不发布、不推送。
- 保留分层不变量；不改模型、命令历史和依赖锁文件。
- 仅增量验证；Windows 构建及安装未执行时必须明确标注。
- 源码默认版本 0.1.0；升级验证版本覆盖只影响构建产物，并记录源码提交。

## Review Focus

- 中文和空格路径：PowerShell 使用参数数组、LiteralPath 和绝对路径。
- GUI 无控制台：日志重定向，布局进程使用控制台辅助 exe 和 UTF-8。
- spawn：冻结入口首先调用 freeze_support，避免递归打开窗口。
- 升级：固定 AppId，旧依赖不残留，用户数据不位于受管目录。
- 构建失败：外部命令非零立即失败；不生成伪成功记录。

### Task 1: 冻结启动及布局进程

Files: scripts/windows/launcher.py, src/mycad/cli/legacy_dxf.py,
tests/ui/test_windows_launcher.py, tests/cli/test_frozen_legacy_layout.py.

- [x] 行为测试：真实布局 JSON 子进程、冻结辅助 exe 路径和故障日志。
- [x] 实现 GUI/CLI 分发和早期 freeze_support；仅对冻结环境改布局命令。
- [x] 运行上述定向测试及改动路径 lint/type 检查。

### Task 2: 本机构建与安装配置

Files: scripts/windows/build.ps1, scripts/windows/mycad.spec,
scripts/windows/installer.iss, scripts/windows/build_support.py,
scripts/windows/requirements-build.txt.

- [x] 独立构建环境导出冻结运行依赖；固定构建器版本，记录实际闭包。
- [x] 生成版本资源、分发记录和第三方授权目录；测试真实文件输出。
- [x] 打包两个入口，共享内部目录；安装日志、快捷方式、升级及卸载配置。
- [x] 在本机检查 Python 逻辑和配置；Windows 编译/运行列为待执行。

### Task 3: 主机操作脚本及清单

Files: scripts/windows/install.ps1, docs/windows-installer-testing.md, README.md.

- [x] 安装/卸载命令显式等待并保存日志、退出码；不自动操作用户数据。
- [x] 写出前置工具、本机构建、安装、升级、卸载和故障取证命令。
- [x] 清单结果初始全部待测；提供证据表和用户数据保留检查。
- [x] 一次独立代码审查，仅修复实际问题；不重复已通过且未受影响的验证。

## 执行记录

本轮仅交付本机准备，不接入远端 CI，不提交或推送；沿用当前 codex 分支。
Windows 原生编译及生命周期验收均待用户主机执行。
定向测试已覆盖启动日志/UTF-8 布局进程/冻结辅助程序命令/构建证据和分层；
既有旧版 DXF 导出相关回归通过。PowerShell 仅做语法树检查，不能替代 Windows 执行。
独立审查指出的 PS5.1 stderr、参数引号和 Windows 日志句柄冲突已修正。
