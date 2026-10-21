param([string]$Symbol='EURUSDm')
$ErrorActionPreference='Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$python=Join-Path (Get-Location) '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $python)) { throw 'Run setup-windows.ps1 first.' }
# The exporter never reads process environment values, browser storage, account
# logins, the trading database, raw event logs, or terminal credential files.
$destination=Join-Path 'runtime' ('support-observation-'+[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffffffZ')+'.json')
& $python -m backend.observation --symbol $Symbol --report --output $destination
$reportExit=$LASTEXITCODE
if (!(Test-Path -LiteralPath $destination -PathType Leaf)) { throw 'Support report generation failed; no current report exists.' }
$report=Get-Content -LiteralPath $destination -Raw | ConvertFrom-Json
if ($report.schema_version -ne 1 -or $report.read_only -ne $true -or $report.demo_observation -ne $true) {
 throw 'Unexpected support report format; inspect the local error before sharing.'
}
if ($reportExit -eq 1 -and $report.verified_demo_samples -eq 0) {
 Write-Host 'There are no verified demo readings yet. The report still documents missing evidence.'
} elseif ($reportExit -ne 0) {
 throw 'Support report command failed; the report was preserved for local inspection.'
}
Write-Host "Review $destination before sharing. It contains observation summaries and database-local account hashes only."
Write-Host 'Do not share your runtime databases, session token, .env, terminal data folders or an unredacted PowerShell screenshot.'
