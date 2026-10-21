param(
 [string]$Symbol='EURUSDm',
 [ValidateRange(0.001,8760)][double]$Hours=24,
 [ValidateRange(1,86400)][double]$IntervalSeconds=60,
 [switch]$Sample,
 [switch]$ReportOnly,
 [switch]$ResetComparison,
 [string]$TerminalPath=''
)
$ErrorActionPreference='Stop'
if ($Sample -and $ReportOnly) { throw 'Choose Sample or ReportOnly, not both.' }
if ($ReportOnly -and $ResetComparison) { throw 'ResetComparison requires a new sample; it cannot change existing reports.' }
Set-Location (Split-Path $PSScriptRoot -Parent)
$python=Join-Path (Get-Location) '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $python)) { throw 'Run setup-windows.ps1 first.' }
if ($TerminalPath) {
 if (!(Test-Path -LiteralPath $TerminalPath -PathType Leaf)) { throw 'TerminalPath must point to the intended MT5 terminal64.exe.' }
 $env:MT5_TERMINAL_PATH=$TerminalPath
}
$arguments=@('-m','backend.observation','--symbol',$Symbol,'--duration-hours',$Hours.ToString([Globalization.CultureInfo]::InvariantCulture),'--interval-seconds',$IntervalSeconds.ToString([Globalization.CultureInfo]::InvariantCulture),'--output','runtime\observation-report.json')
if ($Sample) { $arguments+='--sample' }
if ($ReportOnly) { $arguments+='--report' }
if ($ResetComparison) { $arguments+='--reset-comparison' }
Write-Host 'Read-only observer: no orders, login changes or automation enablement. Keep MT5 open; Ctrl+C stops observation.'
Write-Host 'The report records actual sampled duration. Requested hours are not claimed as completed testing.'
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw 'No verified demo readings, or observation failed. Inspect the allowlisted report; no success evidence was invented.' }
