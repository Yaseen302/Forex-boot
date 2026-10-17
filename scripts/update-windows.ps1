param([ValidateSet('synthetic','mt5')][string]$Source='mt5')
$ErrorActionPreference='Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue) {
 throw 'Port 8000 is in use. In the old ForexLab server window press Ctrl+C, then rerun this update. No process was stopped automatically.'
}
$changes=& git.exe status --porcelain
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect this checkout; no update was attempted.' }
if ($changes) { throw 'Local project changes found; they were preserved. Review them before updating.' }
& git.exe pull --ff-only origin main
if ($LASTEXITCODE -ne 0) { throw 'Git update failed; existing work was preserved.' }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'setup-windows.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Setup/tests failed; application was not started.' }
Write-Host 'Starting read-only analysis. Demo execution requires a separate explicit start with -EnableDemo.'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'start-windows.ps1') -Source $Source
exit $LASTEXITCODE
