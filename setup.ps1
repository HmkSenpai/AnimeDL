# AnimeDL — installation locale (Windows)
# Usage :  powershell -ExecutionPolicy Bypass -File .\setup.ps1
#          powershell -ExecutionPolicy Bypass -File .\setup.ps1 -ForceChromium
#          powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Python 3.13
#          powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Check
#
# Python 3.10 a 3.13 requis : PyYAML et greenlet n'ont pas encore de wheels
# pour 3.14/3.15 (compilation C++ demandee, donc MSVC).

param(
    [switch]$ForceChromium,
    [switch]$NoInstall,
    [switch]$Check,
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$MIN_MINOR = 10
$MAX_MINOR = 13

function Get-PyVersion($launcher) {
    try {
        $out = & $launcher.exe @($launcher.args) -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $out) { return $null }
        return [version]$out.Trim()
    } catch {
        return $null
    }
}

function Test-Supported($version) {
    return $version -and $version.Major -eq 3 -and $version.Minor -ge $MIN_MINOR -and $version.Minor -le $MAX_MINOR
}

Write-Host "==> Recherche d'un Python 3.$MIN_MINOR - 3.$MAX_MINOR"

$launchers = @()
if ($Python) {
    $launchers += @{ name = "py -$Python"; exe = "py"; args = @("-$Python") }
}
foreach ($minor in 13..10) {
    $launchers += @{ name = "py -3.$minor"; exe = "py"; args = @("-3.$minor") }
}
$launchers += @{ name = "python"; exe = "python"; args = @() }

$selected = $null
foreach ($launcher in $launchers) {
    $version = Get-PyVersion $launcher
    if (-not $version) { continue }
    if (Test-Supported $version) {
        $selected = $launcher
        $selectedVersion = $version
        break
    }
    Write-Host ("    ignore : {0} -> Python {1}" -f $launcher.name, $version)
}

if (-not $selected) {
    Write-Host ""
    Write-Host "Aucun Python compatible trouve (3.$MIN_MINOR a 3.$MAX_MINOR)." -ForegroundColor Yellow
    Write-Host "Le Python installe est probablement trop recent : PyYAML/greenlet n'ont pas"
    Write-Host "de wheels pour 3.14/3.15, pip tente donc de compiler et reclame Visual C++."
    Write-Host ""

    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget -and -not $NoInstall) {
        Write-Host "==> Installation de Python 3.13 via winget"
        winget install -e --id Python.Python.3.13 --source winget `
            --accept-package-agreements --accept-source-agreements
        $launchers = @(@{ name = "py -3.13"; exe = "py"; args = @("-3.13") })
        foreach ($launcher in $launchers) {
            $version = Get-PyVersion $launcher
            if (Test-Supported $version) {
                $selected = $launcher
                $selectedVersion = $version
                break
            }
        }
    }

    if (-not $selected) {
        Write-Host "Installe Python 3.13 a la main :" -ForegroundColor Yellow
        Write-Host "  winget install -e --id Python.Python.3.13"
        Write-Host "  ou https://www.python.org/downloads/release/python-3139/"
        Write-Host "Puis relance :  powershell -ExecutionPolicy Bypass -File .\setup.ps1"
        exit 1
    }
}

Write-Host ("    Python {0} via {1}" -f $selectedVersion, $selected.name)

if ($Check) {
    Write-Host "==> Check termine (aucune modification)"
    exit 0
}

Write-Host "==> Environnement virtuel (.venv)"
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    $venvVersion = Get-PyVersion @{ exe = $venvPython; args = @() }
    if (-not (Test-Supported $venvVersion)) {
        Write-Host ("    .venv actuel en Python {0} -> recreation" -f $venvVersion)
        Remove-Item -Recurse -Force ".venv"
    }
}
if (-not (Test-Path $venvPython)) {
    & $selected.exe @($selected.args) -m venv .venv
}

Write-Host "==> Installation des Dependances"
& $venvPython -m pip install --upgrade pip --quiet
& $venvPython -m pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Echec de l'installation des dependances." -ForegroundColor Red
    Write-Host "Si tu vois 'Microsoft Visual C++ 14.0 is required', ton Python est trop recent."
    Write-Host "Relance avec :  .\setup.ps1 -Python 3.13"
    exit 1
}

$candidates = @(
    "C:\Program Files\Google\Chrome\Application\chrome.exe",
    "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
    "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    "$env:LOCALAPPDATA\BraveSoftware\Brave-Browser\Application\brave.exe"
)
$installed = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($installed -and -not $ForceChromium) {
    Write-Host "==> Chromium ignore : navigateur deja installe"
    Write-Host "    $installed"
    Write-Host "    (relance avec -ForceChromium si tu veux le Chromium embarque)"
} else {
    Write-Host "==> Chromium Playwright (~250 Mo)"
    & $venvPython -m playwright install chromium
}

Write-Host ""
Write-Host ("Installation terminee avec Python {0}." -f $selectedVersion)
Write-Host "Lance AnimeDL.bat (ou .\.venv\Scripts\python.exe app.py)."
