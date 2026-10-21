$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (!(Get-Command py -ErrorAction SilentlyContinue)) { throw 'Install 64-bit Python 3.11, reopen PowerShell, then rerun. See docs/WINDOWS.md.' }
if (!(Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw 'Install Node.js LTS, reopen PowerShell, then rerun.' }
& py -3.11 -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 venv creation failed' }
& .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
Push-Location frontend
try {
 & npm.cmd ci --no-audit --no-fund
 if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }
 & npm.cmd test
 if ($LASTEXITCODE -ne 0) { throw 'Indicator/symbol regression checks failed' }
 & npm.cmd run build
 if ($LASTEXITCODE -ne 0) { throw 'Dashboard build failed' }
} finally { Pop-Location }
& .\.venv\Scripts\python.exe -m pytest -q -ra
if ($LASTEXITCODE -ne 0) { throw 'Tests failed; resolve before demo connection' }
Write-Host 'Installed and tested. Next: .\scripts\start-windows.ps1'
