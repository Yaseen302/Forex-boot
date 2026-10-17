param([string]$Symbol='EURUSD', [string]$TerminalPath='')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (!(Test-Path '.venv\Scripts\python.exe')) { throw 'Run setup-windows.ps1 first' }
if ($TerminalPath) {
    if (!(Test-Path -LiteralPath $TerminalPath -PathType Leaf)) { throw 'TerminalPath must point to the intended MT5 terminal64.exe' }
    $env:MT5_TERMINAL_PATH=$TerminalPath
}
Write-Host 'Read-only MT5 check. No orders will be sent. Keep the Exness desktop terminal open.'
& .\.venv\Scripts\python.exe -m backend.diagnostics --symbol $Symbol
if ($LASTEXITCODE -ne 0) { throw 'MT5 data preflight did not pass. Follow the actions in the report and retry.' }
