param([ValidateSet('synthetic','mt5')][string]$Source='synthetic',[switch]$EnableDemo,[string]$TerminalPath='')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (!(Test-Path '.venv\Scripts\python.exe')) { throw 'Run setup-windows.ps1 first' }
if ($EnableDemo -and $Source -ne 'mt5') { throw 'Demo orders require MT5 data' }
if ($TerminalPath) { $env:MT5_TERMINAL_PATH=$TerminalPath }
$env:DATA_SOURCE=$Source
$env:ENABLE_DEMO_EXECUTION=if ($EnableDemo) { '1' } else { '0' }
$env:API_TOKEN=& .\.venv\Scripts\python.exe -c 'import secrets; print(secrets.token_urlsafe(32))'
if ($LASTEXITCODE -ne 0) { throw 'Token generation failed' }
Write-Host 'Copy this session token into the local dashboard (do not share it):'
Write-Host $env:API_TOKEN
Write-Host 'Open http://127.0.0.1:8000 on this PC. Keep this window and MT5 open.'
& .\.venv\Scripts\python.exe -m uvicorn backend.api:app --host 127.0.0.1 --port 8000 --workers 1
