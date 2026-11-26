# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
# Run only on a disposable Windows test account: installs and uninstalls MyCAD.
[CmdletBinding()]
param([string]$BuildRoot = '')
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:OS -ne 'Windows_NT') { throw 'Windows required.' }
$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
if (-not $BuildRoot) {
    $BuildRoot = (Get-ChildItem -LiteralPath (Join-Path $RepoRoot '.mycad-dist/windows') -Directory |
        Sort-Object Name -Descending | Select-Object -First 1).FullName
}
$Setup = Get-ChildItem -LiteralPath $BuildRoot -Filter 'MyCAD-*-x64-Setup.exe' | Select-Object -First 1
if (-not $Setup) { throw 'No installer.' }
$Evidence = Join-Path $BuildRoot 'smoke'
$AppRoot = Join-Path $Evidence 'MyCAD installed'
if (Test-Path -LiteralPath $AppRoot) { throw 'Smoke directory already exists; select a fresh build.' }
$ExistingInstall = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{D2CF3854-9EE0-43CE-8B72-779D88DA685E}_is1'
if (Test-Path -LiteralPath $ExistingInstall) { throw 'Use a disposable account without an existing MyCAD installation.' }
New-Item -ItemType Directory -Path $Evidence -Force | Out-Null
& (Join-Path $PSScriptRoot 'install.ps1') -Action Install -PackagePath $Setup.FullName -InstallDir $AppRoot -EvidenceDir (Join-Path $Evidence 'install') -Silent
$Gui = $null
try {
    $Cli = Join-Path $AppRoot 'MyCAD-cli.exe'
    $Output = & $Cli commands --json
    if ($LASTEXITCODE -ne 0) { throw 'Installed CLI failed.' }
    $Output | Set-Content -LiteralPath (Join-Path $Evidence 'commands.json') -Encoding UTF8
    $Output | ConvertFrom-Json | Out-Null

    # Build geometry from a plan outside the source and installation directories.
    $Plan = Join-Path $Evidence 'flange.json'
    Copy-Item -LiteralPath (Join-Path $RepoRoot 'examples/flange_plan.json') -Destination $Plan
    & $Cli run --json $Plan *> (Join-Path $Evidence 'flange.log')
    if ($LASTEXITCODE -ne 0) { throw 'Installed geometry/archive export failed.' }
    foreach ($Extension in @('step', 'stl', 'mc.json')) {
        $File = Join-Path $Evidence "flange.$Extension"
        if (-not (Test-Path -LiteralPath $File) -or (Get-Item -LiteralPath $File).Length -eq 0) {
            throw "Missing geometry output: $File"
        }
    }
    $Gui = Start-Process -FilePath (Join-Path $AppRoot 'MyCAD.exe') -WorkingDirectory $Evidence -PassThru
    $Deadline = (Get-Date).AddSeconds(90)
    do {
        Start-Sleep -Milliseconds 500
        $Gui.Refresh()
        if ($Gui.HasExited) { throw "GUI exited prematurely: $($Gui.ExitCode)" }
    } until ($Gui.MainWindowHandle -ne 0 -or (Get-Date) -gt $Deadline)
    if ($Gui.MainWindowHandle -eq 0) { throw 'GUI did not create a window.' }
    if (-not $Gui.CloseMainWindow()) { throw 'GUI refused a normal close request.' }
    if (-not $Gui.WaitForExit(30000)) { throw 'GUI did not exit normally.' }
    if ($Gui.ExitCode -ne 0) { throw "GUI exit code: $($Gui.ExitCode)" }
}
finally {
    if ($null -ne $Gui -and -not $Gui.HasExited) {
        # Only this test-owned process is terminated; never discover/kill by app name.
        $Gui.Kill()
        $Gui.WaitForExit()
    }
    $Logs = Join-Path $env:LOCALAPPDATA 'MyCAD/logs'
    if (Test-Path -LiteralPath $Logs) { Copy-Item -LiteralPath $Logs -Destination (Join-Path $Evidence 'application-logs') -Recurse }
    & (Join-Path $PSScriptRoot 'install.ps1') -Action Uninstall -PackagePath (Join-Path $AppRoot 'unins000.exe') -EvidenceDir (Join-Path $Evidence 'uninstall') -Silent
}
if (Test-Path -LiteralPath (Join-Path $AppRoot 'MyCAD.exe')) { throw 'Executable remains after uninstall.' }
if (Test-Path -LiteralPath $ExistingInstall) { throw 'Uninstall registration remains after uninstall.' }
@{status='passed'; installer=$Setup.Name; scope='install, CLI JSON, geometry/archive export, GUI window, normal close and uninstall'; timestamp=(Get-Date).ToString('o')} |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Evidence 'smoke-result.json') -Encoding UTF8
