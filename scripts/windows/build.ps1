# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
# Run from Windows PowerShell 5.1+ or PowerShell 7. No administrator rights needed.
[CmdletBinding()]
param(
    [ValidateRange(0, 65535)][int]$Revision = 0,
    [string]$IsccPath = '',
    [string]$IconPath = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:OS -ne 'Windows_NT') { throw 'Build this package on Windows x64.' }
if (-not [Environment]::Is64BitOperatingSystem) { throw 'Windows x64 is required.' }
$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
Get-Command uv -ErrorAction Stop | Out-Null
Get-Command git -ErrorAction Stop | Out-Null
if (-not $IsccPath) {
    $Candidate = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6/ISCC.exe'
    if (Test-Path -LiteralPath $Candidate) { $IsccPath = $Candidate }
    else { $IsccPath = (Get-Command ISCC.exe -ErrorAction Stop).Source }
}
$IsccPath = (Resolve-Path -LiteralPath $IsccPath).Path
$CompilerVersion = (Get-Item -LiteralPath $IsccPath).VersionInfo.FileVersion
# ISCC.exe's file resource is not the compiler-engine version. The .iss file
# checks the authoritative VER preprocessor constant when compilation starts.
if (-not (Test-Path -LiteralPath (Join-Path (Split-Path $IsccPath) 'Languages/ChineseSimplified.isl'))) {
    throw 'Install Inno Setup 6.5+ with its bundled Simplified Chinese translation.'
}
if ($IconPath) { $IconPath = (Resolve-Path -LiteralPath $IconPath).Path }
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$BuildRoot = Join-Path $RepoRoot ".mycad-dist/windows/$Stamp-r$Revision"
New-Item -ItemType Directory -Path $BuildRoot -Force | Out-Null
$NativeLog = Join-Path $BuildRoot 'commands.log'
Start-Transcript -LiteralPath (Join-Path $BuildRoot 'build.log') | Out-Null
Write-Host "ISCC file resource (informational): $CompilerVersion; PowerShell: $($PSVersionTable.PSVersion)"

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    Write-Host "Running: $Program $($Arguments -join ' ')"
    # Windows PowerShell 5.1 turns native stderr into ErrorRecords. uv writes
    # normal progress there; let the process exit code determine success.
    $PreviousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $Program @Arguments 2>&1 | Tee-Object -FilePath $NativeLog -Append | Out-Host
        $CommandExitCode = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $PreviousPreference }
    if ($CommandExitCode -ne 0) { throw "Command failed ($CommandExitCode): $Program" }
}

$PreviousBuildRoot = $env:MYCAD_BUILD_ROOT
$PreviousIcon = $env:MYCAD_BUILD_ICON
Push-Location $RepoRoot
try {
    $Python = Join-Path $BuildRoot 'venv/Scripts/python.exe'
    Invoke-Checked uv @('venv', '--python', '3.12', (Join-Path $BuildRoot 'venv'))
    Invoke-Checked $Python @('-c', "import platform,struct,sys; assert sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8 and platform.machine().upper() in ('AMD64','X86_64'), 'CPython 3.12 x64 required'")
    $Requirements = Join-Path $BuildRoot 'runtime-requirements.txt'
    Invoke-Checked uv @('export', '--frozen', '--no-dev', '--no-editable', '--no-emit-project', '--extra', 'desktop', '--extra', 'sketch-constraints', '--output-file', $Requirements)
    Invoke-Checked uv @('pip', 'install', '--python', $Python, '-r', $Requirements, '-r', (Join-Path $PSScriptRoot 'requirements-build.txt'))
    Invoke-Checked uv @('pip', 'install', '--python', $Python, '--no-deps', $RepoRoot)
    Invoke-Checked $Python @((Join-Path $PSScriptRoot 'build_support.py'), '--root', $RepoRoot, '--output', $BuildRoot, '--revision', "$Revision")
    @("Inno Setup=$CompilerVersion", "PowerShell=$($PSVersionTable.PSVersion)", "ISCC SHA256=$((Get-FileHash -LiteralPath $IsccPath -Algorithm SHA256).Hash)") | Set-Content -LiteralPath (Join-Path $BuildRoot 'build-environment.txt') -Encoding UTF8
    $env:MYCAD_BUILD_ROOT = $BuildRoot
    $env:MYCAD_BUILD_ICON = $IconPath
    Invoke-Checked $Python @('-m', 'PyInstaller', '--noconfirm', '--clean', '--distpath', (Join-Path $BuildRoot 'dist'), '--workpath', (Join-Path $BuildRoot 'pyinstaller'), (Join-Path $PSScriptRoot 'mycad.spec'))
    $Version = (Get-Content -LiteralPath (Join-Path $BuildRoot 'version.txt') -Raw).Trim()
    $CompilerArguments = @("/DSourceDir=$(Join-Path $BuildRoot 'dist/MyCAD')", "/DOutputDir=$BuildRoot", "/DAppVersion=$Version")
    if ($IconPath) { $CompilerArguments += "/DIconPath=$IconPath" }
    $CompilerArguments += (Join-Path $PSScriptRoot 'installer.iss')
    Invoke-Checked $IsccPath $CompilerArguments
    Invoke-Checked $Python @((Join-Path $PSScriptRoot 'build_support.py'), '--output', $BuildRoot, '--finalize')
    Write-Host "Build artifacts: $BuildRoot"
    Write-Host 'Installer compiled. Windows functional and lifecycle checks are still pending.'
}
catch {
    $_ | Out-String | Set-Content -LiteralPath (Join-Path $BuildRoot 'FAILED.txt') -Encoding UTF8
    throw
}
finally {
    $env:MYCAD_BUILD_ROOT = $PreviousBuildRoot
    $env:MYCAD_BUILD_ICON = $PreviousIcon
    Pop-Location
    Stop-Transcript | Out-Null
}
