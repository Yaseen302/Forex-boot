param([string]$TerminalPath='')
$ErrorActionPreference='Stop'
# Optional Task Scheduler entry point. Registration is a separate, reviewed step.
# A single interactive user session owns this backend; never use --reload/workers >1.
$mutex=New-Object System.Threading.Mutex($false,'Local\ForexLab-Analysis-8000')
$acquired=$false
try {
 try { $acquired=$mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $acquired=$true }
 if (!$acquired) { throw 'ForexLab startup is already active. Use its existing server window.' }
 $listener=Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue
 if ($listener) { throw 'Port 8000 already has a server. This launcher will not start a second backend or stop the existing process.' }
 $project=Split-Path $PSScriptRoot -Parent
 Set-Location $project
 # Intentionally analysis-only: execution and automation need fresh manual opt-in.
 & (Join-Path $PSScriptRoot 'start-windows.ps1') -Source mt5 -TerminalPath $TerminalPath
 if ($LASTEXITCODE -ne 0) { throw 'ForexLab server stopped with an error. Review the server window before restarting.' }
} finally {
 if ($acquired) { $mutex.ReleaseMutex() }
 $mutex.Dispose()
}
