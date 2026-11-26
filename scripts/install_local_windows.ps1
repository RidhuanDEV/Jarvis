<#
.SYNOPSIS
    Portable Per-User Local Windows Installer for J.A.R.V.I.S. (DEC-018, zero admin required).
.DESCRIPTION
    1. Builds (unless -SkipBuild is passed) the Tauri 2 Windows x64 NSIS Minimal Base Installer.
    2. Provisions the portable Python Core runtime pointer under %LOCALAPPDATA%\JarvisOS\Jarvis\runtime-pointer.json
       pointing to the local core/.venv (zero hardcoded developer paths in source code).
    3. Installs J.A.R.V.I.S. silently for the current user via NSIS (/S) and verifies the installed executable.
#>
[CmdletBinding()]
param(
    [switch]$SkipBuild,
    [switch]$LaunchAfterInstall
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$CoreDir = Join-Path $RepoRoot "core"
$CorePython = Join-Path $CoreDir ".venv\Scripts\python.exe"
$DesktopDir = Join-Path $RepoRoot "apps\desktop"

if (-not (Test-Path $CorePython)) {
    throw "Python Core virtual environment not found at '$CorePython'. Run 'cd core && uv sync --frozen' first."
}

if (-not $env:CARGO_TARGET_DIR) {
    $env:CARGO_TARGET_DIR = Join-Path $env:LOCALAPPDATA "Jarvis-Build-Cache\cargo-target"
}

if (-not $SkipBuild) {
    Write-Host "[1/3] Building J.A.R.V.I.S. Windows x64 per-user NSIS installer..."
    Push-Location $DesktopDir
    try {
        npx tauri build --bundles nsis
        if ($LASTEXITCODE -ne 0) {
            throw "Tauri NSIS build failed with exit code $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }
}

$Installer = Get-ChildItem -Path (Join-Path $env:CARGO_TARGET_DIR "release\bundle\nsis") -Filter "*-setup.exe" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1

if (-not $Installer) {
    throw "NSIS installer not found under '$env:CARGO_TARGET_DIR\release\bundle\nsis'. Re-run without -SkipBuild."
}

Write-Host "[2/3] Writing per-user portable runtime pointer under %LOCALAPPDATA%\JarvisOS\Jarvis\runtime-pointer.json..."
$RuntimeCfgDir = Join-Path $env:LOCALAPPDATA "JarvisOS\Jarvis"
New-Item -ItemType Directory -Force -Path $RuntimeCfgDir | Out-Null
$PointerObj = [ordered]@{
    schema_version = 1
    python_exe     = $CorePython
    core_dir       = $CoreDir
}
$PointerPath = Join-Path $RuntimeCfgDir "runtime-pointer.json"
$PointerJson = $PointerObj | ConvertTo-Json
[System.IO.File]::WriteAllText($PointerPath, $PointerJson, [System.Text.UTF8Encoding]::new($false))

Write-Host "[3/3] Installing J.A.R.V.I.S. per-user (silent NSIS /S, zero admin): $($Installer.FullName)"
$proc = Start-Process -FilePath $Installer.FullName -ArgumentList "/S" -Wait -PassThru
if ($proc.ExitCode -ne 0) {
    throw "NSIS installer exited with code $($proc.ExitCode)"
}

$InstalledExe = Join-Path $env:LOCALAPPDATA "J.A.R.V.I.S.\jarvis-desktop.exe"
if (-not (Test-Path $InstalledExe)) {
    # Fallback search if NSIS chose productName subfolder variant
    $Found = Get-ChildItem -Path $env:LOCALAPPDATA -Filter "jarvis-desktop.exe" -Recurse -Depth 2 -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($Found) { $InstalledExe = $Found.FullName }
}

if (-not (Test-Path $InstalledExe)) {
    throw "Installation completed, but jarvis-desktop.exe was not found under %LOCALAPPDATA%."
}

Write-Host "SUCCESS: J.A.R.V.I.S. installed at '$InstalledExe'"
Write-Host "Runtime pointer configured at '$PointerPath'"

if ($LaunchAfterInstall) {
    Write-Host "Launching installed J.A.R.V.I.S. desktop application..."
    Start-Process -FilePath $InstalledExe
}
