#Requires -Version 5.1
<#
.SYNOPSIS
    Pull latest changes, extract libs if missing, sync deps, and launch the app.

.NOTES
    7-Zip is required to extract lib.7z on first run.
    Place 7za.exe (standalone 7-Zip console) in .\tools\7za.exe, or install
    7-Zip system-wide (https://7-zip.org).
#>

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Write-Step  { param($msg) Write-Host "  $msg" -ForegroundColor Cyan }
function Write-Ok    { param($msg) Write-Host "  $msg" -ForegroundColor Green }
function Write-Fail  { param($msg) Write-Host "  ERROR: $msg" -ForegroundColor Red }

Write-Host ""
Write-Host " Music Player — startup" -ForegroundColor White
Write-Host " ─────────────────────────────────────" -ForegroundColor DarkGray

# ── 1. git pull ──────────────────────────────────────────────────────────────
Write-Step "Pulling latest changes..."
git pull
if ($LASTEXITCODE -ne 0) {
    Write-Fail "git pull failed (exit $LASTEXITCODE). Continuing with local files."
}

# ── 2. Extract lib/ if missing ───────────────────────────────────────────────
if (-not (Test-Path ".\lib")) {
    Write-Step "lib\ not found — extracting lib.7z..."

    $archive = ".\lib.7z"
    if (-not (Test-Path $archive)) {
        Write-Fail "lib.7z not found. Cannot extract native libraries."
        Write-Host "  Place lib.7z in the project root and re-run." -ForegroundColor Yellow
        Read-Host "`n  Press Enter to exit"
        exit 1
    }

    # Locate 7-Zip: bundled first, then common install paths, then PATH
    $sevenZip = $null
    $candidates = @(
        ".\tools\7za.exe",
        "C:\Program Files\7-Zip\7z.exe",
        "C:\Program Files (x86)\7-Zip\7z.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $sevenZip = $c; break }
    }
    if (-not $sevenZip) {
        $found = Get-Command 7z -ErrorAction SilentlyContinue
        if ($found) { $sevenZip = $found.Source }
    }

    if (-not $sevenZip) {
        Write-Fail "7-Zip not found."
        Write-Host "  Install 7-Zip from https://7-zip.org" -ForegroundColor Yellow
        Write-Host "  or place 7za.exe in .\tools\7za.exe" -ForegroundColor Yellow
        Read-Host "`n  Press Enter to exit"
        exit 1
    }

    & $sevenZip x $archive -o"$PSScriptRoot" -y | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Extraction failed (exit $LASTEXITCODE)."
        Read-Host "`n  Press Enter to exit"
        exit 1
    }
    Write-Ok "lib\ extracted."
} else {
    Write-Ok "lib\ already present."
}

# ── 3. uv sync ───────────────────────────────────────────────────────────────
Write-Step "Syncing Python dependencies..."
uv sync --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Fail "uv sync failed (exit $LASTEXITCODE)."
    Read-Host "`n  Press Enter to exit"
    exit 1
}
Write-Ok "Dependencies up to date."

# ── 4. Launch ────────────────────────────────────────────────────────────────
Write-Host ""
Write-Step "Starting Music Player..."
Write-Host ""
uv run .\main.py
