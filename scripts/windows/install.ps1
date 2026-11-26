# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('Install', 'Uninstall')][string]$Action,
    [Parameter(Mandatory = $true)][string]$PackagePath,
    [string]$InstallDir = '',
    [string]$EvidenceDir = '',
    [switch]$Silent
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:OS -ne 'Windows_NT') { throw 'This script must run on Windows.' }
$Executable = (Resolve-Path -LiteralPath $PackagePath).Path
if (-not $EvidenceDir) {
    $EvidenceDir = Join-Path $env:LOCALAPPDATA ('MyCAD/installer-logs/' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
}
$EvidenceDir = [IO.Path]::GetFullPath($EvidenceDir)
New-Item -ItemType Directory -Path $EvidenceDir -Force | Out-Null
$LogPath = Join-Path $EvidenceDir "$Action.log"
$Arguments = @('/NORESTART', "/LOG=`"$LogPath`"")
if ($Silent) { $Arguments += @('/VERYSILENT', '/SUPPRESSMSGBOXES') }
if ($Action -eq 'Install') {
    # Never close an application with potentially unsaved documents during an unattended install.
    $Arguments += '/NOCLOSEAPPLICATIONS'
    if ($InstallDir) {
        $InstallDir = [IO.Path]::GetFullPath($InstallDir)
        if ($InstallDir.Contains('"')) { throw 'Invalid quote in installation directory.' }
        $Arguments += "/DIR=`"$InstallDir`""
    }
}
elseif ($InstallDir) { throw '-InstallDir is only valid for Install.' }
$PackageHash = (Get-FileHash -LiteralPath $Executable -Algorithm SHA256).Hash.ToLowerInvariant()
$Process = Start-Process -FilePath $Executable -ArgumentList $Arguments -PassThru -Wait
$Result = [ordered]@{
    action = $Action
    package = $Executable
    sha256 = $PackageHash
    exitCode = $Process.ExitCode
    log = $LogPath
    installDir = $InstallDir
    silent = [bool]$Silent
    completed = (Get-Date).ToString('o')
}
$Result | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $EvidenceDir "$Action-result.json") -Encoding UTF8
Write-Host "Exit code: $($Process.ExitCode); evidence: $EvidenceDir"
if ($Process.ExitCode -ne 0 -and $Process.ExitCode -ne 3010) {
    throw "Installer did not complete successfully (exit $($Process.ExitCode)). See $LogPath"
}
if ($Process.ExitCode -eq 3010) { Write-Warning 'Installation requires a Windows restart.' }
