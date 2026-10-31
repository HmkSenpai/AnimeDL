# AnimeDL — installation locale (Windows)
# Usage :  powershell -ExecutionPolicy Bypass -File .\setup.ps1
#          powershell -ExecutionPolicy Bypass -File .\setup.ps1 -ForceChromium

param([switch]$ForceChromium)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "==> Python"
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "Python introuvable. Installe Python 3.11+ depuis https://www.python.org/downloads/windows/"
    Write-Host "(coche 'Add python.exe to PATH' pendant l'installation)"
    exit 1
}
python --version

Write-Host "==> Environnement virtuel (.venv)"
if (-not (Test-Path ".venv")) {
    python -m venv .venv
}
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

Write-Host "==> Dépendances"
& $py -m pip install --upgrade pip --quiet
& $py -m pip install -r requirements.txt --quiet

# Un Chrome / Edge / Brave déjà présent suffit : Playwright le pilote sans téléchargement.
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
    Write-Host "==> Chromium ignoré : navigateur déjà installé"
    Write-Host "    $installed"
    Write-Host "    (relance avec -ForceChromium si tu veux le Chromium embarqué)"
} else {
    Write-Host "==> Chromium Playwright (~250 Mo)"
    & $py -m playwright install chromium
}

Write-Host ""
Write-Host "Installation terminée. Lance AnimeDL.bat (ou .\.venv\Scripts\python.exe app.py)."
