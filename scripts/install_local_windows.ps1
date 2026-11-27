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

# Discover optional local AI runtimes & models (zero hardcoded paths; skip empty folders)
$RuntimesDir = $null
foreach ($cand in @(
    (Join-Path $RuntimeCfgDir "runtimes"),
    (Join-Path $env:LOCALAPPDATA "Jarvis-R0-Sandbox\runtimes")
)) {
    if ((Test-Path $cand) -and @(Get-ChildItem -Path $cand -ErrorAction SilentlyContinue).Count -gt 0) {
        $RuntimesDir = $cand
        break
    }
}
$ModelsDir = $null
foreach ($cand in @(
    (Join-Path $RuntimeCfgDir "models"),
    (Join-Path $env:LOCALAPPDATA "Jarvis-R0-Sandbox\models")
)) {
    if ((Test-Path $cand) -and @(Get-ChildItem -Path $cand -ErrorAction SilentlyContinue).Count -gt 0) {
        $ModelsDir = $cand
        break
    }
}

$PointerObj = [ordered]@{
    schema_version = 1
    python_exe     = $CorePython
    core_dir       = $CoreDir
}
if ($RuntimesDir) { $PointerObj["runtimes_dir"] = $RuntimesDir }
if ($ModelsDir) { $PointerObj["models_dir"] = $ModelsDir }

$PointerPath = Join-Path $RuntimeCfgDir "runtime-pointer.json"
$PointerJson = $PointerObj | ConvertTo-Json
[System.IO.File]::WriteAllText($PointerPath, $PointerJson, [System.Text.UTF8Encoding]::new($false))

# Stop any existing running JARVIS desktop instance before upgrading cleanly
Get-Process -Name "jarvis-desktop" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500

# Clean legacy trailing-dot install/shortcut if present from earlier 0.2.1 preview
$LegacyUninst = Join-Path $env:LOCALAPPDATA "J.A.R.V.I.S\uninstall.exe"
if (Test-Path $LegacyUninst) {
    Start-Process -FilePath $LegacyUninst -ArgumentList "/S" -Wait -ErrorAction SilentlyContinue
}
$LegacyLnk = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\J.A.R.V.I.S..lnk"
if (Test-Path $LegacyLnk) { Remove-Item -Force $LegacyLnk -ErrorAction SilentlyContinue }

Write-Host "[3/3] Installing JARVIS per-user (silent NSIS /S, zero admin): $($Installer.FullName)"
$proc = Start-Process -FilePath $Installer.FullName -ArgumentList "/S" -Wait -PassThru
if ($proc.ExitCode -ne 0) {
    throw "NSIS installer exited with code $($proc.ExitCode)"
}

$InstalledExe = Join-Path $env:LOCALAPPDATA "JARVIS\jarvis-desktop.exe"
if (-not (Test-Path $InstalledExe)) {
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
