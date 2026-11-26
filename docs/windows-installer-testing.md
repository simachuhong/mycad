# Windows 本机构建、安装与验收

状态：脚本和安装配置已准备；**Windows 编译、安装与人工操作结果均待执行**。
当前交付为测试安装包准备工作，不代表稳定版发布或专业 CAD 兼容验收通过。

## 1. 构建机准备

目标为 Windows 10/11 x64；请使用普通用户 PowerShell 5.1 或 7，不必以管理员运行。
构建机需安装 [Git for Windows](https://gitforwindows.org/)、
[uv](https://docs.astral.sh/uv/getting-started/installation/) 和
[Inno Setup 6.5+](https://jrsoftware.org/inno-setup/downloads)。
简体中文翻译文件随项目提供，不依赖编译器安装时是否勾选额外语言。
构建需要网络下载 Python 和锁定依赖；安装包使用者不需要安装这些开发工具。

将当前交付的完整仓库放到 Windows，例如 `D:\projects\MyCAD`，
包括 `scripts\windows`、新增源码文件和本文档；仅复制脚本不能构建。
若通过 Git 获取，确认该提交已经包含这些改动；本次准备工作不会自动推送仓库。

```powershell
Set-Location 'D:\projects\MyCAD'
git status --short
uv --version
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\build.ps1 -Revision 1
```

脚本自行创建独立 CPython 3.12 x64 环境，依照 `uv.lock` 导出 `desktop` 和
`sketch-constraints` 运行依赖，再构建 GUI、CLI 辅助程序和安装器。
它不重写 `uv.lock`，不使用开发 `.venv`，也不运行全量测试。
Python 包索引使用 uv 的配置；不要为了构建改写锁文件或在日志中输出凭证。

自定义编译器或已有 ICO 图标时：

```powershell
.\scripts\windows\build.ps1 -Revision 1 `
  -IsccPath 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe' `
  -IconPath 'D:\branding\MyCAD.ico'
```

未提供 ICO 时使用打包器默认图标；正式品牌图标和数字签名尚未配置。
本轮生成的安装器为未签名测试产物，构建成功也不表示已经完成发布前审核。

## 2. 找到构建结果

```powershell
$Build = Get-ChildItem -LiteralPath '.\.mycad-dist\windows' -Directory |
  Sort-Object Name -Descending | Select-Object -First 1
$Build.FullName
$Setup = Get-ChildItem -LiteralPath $Build.FullName -Filter 'MyCAD-*-x64-Setup.exe' |
  Select-Object -First 1
if (-not $Setup) { throw '未生成安装器，请查看 build.log / commands.log / FAILED.txt' }
Get-Content -LiteralPath (Join-Path $Build.FullName 'SHA256SUMS')
Get-FileHash -LiteralPath $Setup.FullName -Algorithm SHA256
```

每次构建输出到 `.mycad-dist\windows\时间戳-r修订号\`，包含：

| 文件 | 用途 |
|---|---|
| `MyCAD-0.1.0.1-x64-Setup.exe` | 安装器；前三段取自源码版本，第四段取 `-Revision` |
| `SHA256SUMS` | 安装器 SHA256，复制到测试机后再次核对 |
| `build-info.json` | 提交、工作区是否有改动、依赖、锁摘要及待验证状态 |
| `build-environment.txt` | Inno Setup、PowerShell 版本及编译器哈希 |
| `build.log` / `commands.log` | 构建过程与工具输出 |
| `FAILED.txt` | 构建脚本捕获的失败，成功时不存在 |
| `runtime-requirements.txt` | 本次冻结导出的运行依赖 |
| `dist\MyCAD\` | 安装器输入，包含 GUI、CLI 和共享 `_internal` 目录 |
| `payload\third-party-licenses\audit.json` | 构建环境授权文件清单和缺失项；不是授权已完备的结论 |

不要将整个构建目录分发给测试用户：其中包含构建环境及诊断文件。
测试机只需安装器；测试协调者同时保留校验文件、构建记录和检查结果。
发现 `dirty=true` 时，提交号不足以单独重现构建，需保留对应源码快照或补丁。

## 3. 安装及安装日志

为便于收集日志，推荐在仓库目录使用包装脚本启动安装向导：

```powershell
.\scripts\windows\install.ps1 -Action Install -PackagePath $Setup.FullName
```

脚本等待安装结束，默认在 `%LOCALAPPDATA%\MyCAD\installer-logs\时间戳\` 保存
`Install.log` 和 `Install-result.json`，包含安装器路径、哈希和退出码。
`0` 为成功，`3010` 表示需要重启，其他值视为未完成；用户取消也不会被记作成功。
直接双击 Setup.exe 同样会生成 Inno Setup 默认日志，通常位于 `%TEMP%` 的
`Setup Log*.txt`；可按修改时间查找。

指定包含中文和空格的目录，并把证据集中保存：

```powershell
.\scripts\windows\install.ps1 -Action Install -PackagePath $Setup.FullName `
  -InstallDir "$env:LOCALAPPDATA\Programs\MyCAD 测试" `
  -EvidenceDir "$env:USERPROFILE\Desktop\MyCAD-evidence\install"
```

测试机无需复制完整仓库；若需要此包装脚本，只需另带 `install.ps1`。
无脚本也可通过 Windows 命令行显式指定日志：

```powershell
& 'D:\downloads\MyCAD-0.1.0.1-x64-Setup.exe' '/LOG=D:\MyCAD-install.log'
```

默认安装到 `%LOCALAPPDATA%\Programs\MyCAD`，安装范围为当前用户。
安装向导提供桌面快捷方式和“打开方式”关联可选项，默认不勾选。
文件关联向 Windows 登记 MyCAD 为候选程序，不强制覆盖既有默认应用。
程序运行时会持有安装互斥量，安装/卸载应提示先正常关闭 MyCAD；勿依赖强制终止。

## 4. 运行与故障证据

从开始菜单启动 MyCAD，或运行安装目录中的 `MyCAD.exe`。
传入文档路径可以直接打开文件，例如：

```powershell
& "$env:LOCALAPPDATA\Programs\MyCAD\MyCAD.exe" 'D:\测试图纸\法兰.my3d'
& "$env:LOCALAPPDATA\Programs\MyCAD\MyCAD-cli.exe" commands --json
```

如果安装时选择自定义目录，以上路径须对应修改。
默认日志为 `%LOCALAPPDATA%\MyCAD\logs\进程号\application.log`，每个进程单独记录，
应用日志保留最多 3 份轮转历史；窗口程序的标准输出/错误记录到同目录 `stdio.log`，
用于定位 Python/Qt 异常。不同进程目录和 `stdio.log` 不自动清理，可取证后手动归档。
Qt 插件加载失败等原生进程提前退出，可能早于 Python 日志初始化；此时同时保留
Windows 事件查看器“Windows 日志 → 应用程序”对应错误及构建日志。

字体和用户库位置以“字体管理”及库设置实际显示为准；这些资源不应写入安装目录。
日志和构建信息可能含用户名、路径、文件名，分享前可遮去无关个人信息。

## 5. 覆盖升级

先安装 `-Revision 1` 构建，创建图纸、导入可再分发的测试字体、设置一个测试块库，
记录它们的路径并保存文件。关闭应用后构建并安装 `-Revision 2`：

```powershell
.\scripts\windows\build.ps1 -Revision 2
# 按第 2 节重新取得 $Build / $Setup，再启动安装。
.\scripts\windows\install.ps1 -Action Install -PackagePath $Setup.FullName
```

第四段构建修订允许测试安装器升级，不代表新增产品功能。
使用同一 Windows 用户、同一 AppId，不要手动改安装器中的 AppId。
确认仍使用原安装目录，已安装应用列表仅保留一个 MyCAD，版本升至 `0.1.0.2`，
旧图纸、字体、库设置仍可用。再运行旧安装器，应明确拒绝降级。
中途断电等异常导致安装失败时不承诺事务回滚；保留日志后用同版安装器修复安装，
不要删除用户文档或字体目录作为排错步骤。

## 6. 卸载及重新安装

先关闭 MyCAD，再从 Windows“已安装的应用”卸载，或使用包装脚本：

```powershell
.\scripts\windows\install.ps1 -Action Uninstall `
  -PackagePath "$env:LOCALAPPDATA\Programs\MyCAD\unins000.exe" `
  -EvidenceDir "$env:USERPROFILE\Desktop\MyCAD-evidence\uninstall"
```

保存 `Uninstall.log` / `Uninstall-result.json`。程序文件及自有快捷方式/注册项应移除，
用户图纸、字体、块库和偏好设置保留。系统应用列表卸载也启用了默认日志。
重新安装后，确认保留的数据仍可用。不要把“卸载干净”理解为删除用户工作成果。

自动化冒烟时可额外传 `-Silent`；先走通交互安装，再做一次必要的静默安装/卸载验证，
不应以重复执行全套功能测试代替失败定位。运行中的应用应阻止安装，而不是被静默强杀。

## 7. Windows 主机检查清单

初始状态均为**待执行**。每项记“通过/失败/不适用”，附日志路径或截图。
优先在无 Python/uv/源码目录的独立 Windows 测试环境验证安装后的运行。
Windows 11 结果不能自动代表 Windows 10 已验证。

| 编号 | 操作与预期 | 结果/证据 |
|---|---|---|
| W01 | 全新安装：中文向导、许可、目标目录、完成页，无需管理员权限 | 待执行 |
| W02 | 取消安装：未记作成功；无可用的半安装入口 | 待执行 |
| W03 | 中文/空格安装目录和用户目录：成功启动及保存重开 | 待执行 |
| W04 | 开始菜单、可选桌面快捷方式、已安装应用中的版本及卸载入口正确 | 待执行 |
| W05 | 普通目录及任意工作目录启动，无缺 DLL、Qt 插件或重复窗口 | 待执行 |
| W06 | 二维线/圆/尺寸及中文文字；约束求解可用，缺字体有明确反馈 | 待执行 |
| W07 | 三维建模、视口显示/拾取、撤销重做，保存及重开一致 | 待执行 |
| W08 | 工程图生成及更新，spawn 子进程不递归打开主窗口，退出后无遗留进程 | 待执行 |
| W09 | DXF/STEP/PDF 导出；含旧公差框/旧基准图纸的字体布局辅助进程正常 | 待执行 |
| W10 | 可选打开方式关联能打开 .my2d/.my3d，其他程序关联不被强制改写 | 待执行 |
| W11 | 日志存在；失败有可定位证据，不能只凭进程短暂出现判启动成功 | 待执行 |
| W12 | 重复安装同版本可完成，安装/卸载在程序运行中提示先关闭 | 待执行 |
| W13 | 修订 1 → 2 覆盖升级：版本更新、应用列表不重复、用户数据保留 | 待执行 |
| W14 | 修订 2 → 1 降级明确拒绝；其他程序的 _internal 目录不被删除 | 待执行 |
| W15 | 卸载移除受管程序文件/自有入口，保留图纸、字体、库和偏好 | 待执行 |
| W16 | 卸载后重新安装，原文件和保留的资源可继续使用 | 待执行 |
| W17 | 静默安装/卸载日志及退出码正确，运行中应用不被强杀 | 待执行 |

记录环境：Windows 版本/Build、CPU 架构、显卡与驱动、屏幕缩放、用户名是否中文、
安装目录、安装器 SHA256、源码提交和构建修订。失败时提供最短复现步骤，
不要为了重测一个失败项反复运行所有项目。

## 8. 发布前仍需处理

本地构建完成不等于 Gitee 已发布。正式发布前须处理签名、品牌图标、授权清单缺失项、
Windows 实机验收及包体大小；本轮没有创建远端发行版或运行全量测试。
发布文案只能声明已有证据覆盖的平台和功能。
