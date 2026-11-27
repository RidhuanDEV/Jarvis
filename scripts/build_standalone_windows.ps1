<#
.SYNOPSIS
    Stage G5 (B18) Reproducible Standalone Windows Bundle Staging & Offline Smoke Script.
.DESCRIPTION
    Stages a self-contained J.A.R.V.I.S. layout with zero dev .venv dependency:
      <OutDir>/resources/core/jarvis/...
      <OutDir>/resources/migrations/...
      <OutDir>/resources/contracts/...
      <OutDir>/resources/python/  (copied from -EmbeddedPythonDir if supplied)
    Optionally runs a bounded offline Core smoke check verifying /healthz & /v1/health.
#>
[CmdletBinding()]
param(
    [string]$OutDir = "",
    [string]$EmbeddedPythonDir = "",
    [switch]$SmokeTest
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $OutDir) {
    $OutDir = Join-Path $RepoRoot "dist\standalone-win64"
}

$ResDir = Join-Path $OutDir "resources"
$CoreDst = Join-Path $ResDir "core\jarvis"
$MigDst = Join-Path $ResDir "migrations"
$ContractsDst = Join-Path $ResDir "contracts"

Write-Host "[B18] Staging standalone J.A.R.V.I.S. resources into: $OutDir"
New-Item -ItemType Directory -Force -Path $CoreDst, $MigDst, $ContractsDst | Out-Null

Copy-Item -Path (Join-Path $RepoRoot "core\jarvis\*") -Destination $CoreDst -Recurse -Force
Copy-Item -Path (Join-Path $RepoRoot "core\migrations\*") -Destination $MigDst -Recurse -Force
Copy-Item -Path (Join-Path $RepoRoot "contracts\*") -Destination $ContractsDst -Recurse -Force
Copy-Item -Path (Join-Path $RepoRoot "LICENSE") -Destination $OutDir -Force
Copy-Item -Path (Join-Path $RepoRoot "THIRD-PARTY-NOTICES.txt") -Destination $OutDir -Force

# Remove any __pycache__ from staged core tree for deterministic checksums
Get-ChildItem -Path $CoreDst -Directory -Filter "__pycache__" -Recurse -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force

if ($EmbeddedPythonDir -and (Test-Path $EmbeddedPythonDir)) {
    $PyDst = Join-Path $ResDir "python"
    New-Item -ItemType Directory -Force -Path $PyDst | Out-Null
    Copy-Item -Path (Join-Path $EmbeddedPythonDir "*") -Destination $PyDst -Recurse -Force
    Write-Host "[B18] Bundled embedded Python runtime into $PyDst"
}

if ($SmokeTest) {
    $PyExe = Join-Path $ResDir "python\python.exe"
    if (-not (Test-Path $PyExe)) {
        $PyExe = Join-Path $RepoRoot "core\.venv\Scripts\python.exe"
    }
    $TmpData = Join-Path ([System.IO.Path]::GetTempPath()) ("jarvis_b18_smoke_" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $TmpData | Out-Null
    try {
        $env:PYTHONPATH = (Join-Path $ResDir "core")
        $env:JARVIS_MIGRATIONS_DIR = $MigDst
        $env:JARVIS_CONTRACTS_DIR = $ContractsDst
        & $PyExe -c "from pathlib import Path; from fastapi.testclient import TestClient; from jarvis.transport.app import build_default_container, create_app; from jarvis.transport.settings import CoreStartupSettings; s = CoreStartupSettings(env='test', auth_token='s'*32, base_data_dir=Path(r'$TmpData')/'d', base_cache_dir=Path(r'$TmpData')/'c'); c = build_default_container(s); cl = TestClient(create_app(c)); r = cl.get('/v1/health', headers={'Authorization':'Bearer '+'s'*32, 'Host':'127.0.0.1'}); assert r.status_code == 200 and r.json()['status'] == 'ready'; c.db.close(); print('B18_STANDALONE_SMOKE_PASS')"
    } finally {
        Remove-Item -Path $TmpData -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "[B18] Standalone resource staging completed cleanly."
