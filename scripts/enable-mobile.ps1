param([ValidateRange(1024,65535)][int]$Port=8000)
$ErrorActionPreference='Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$client=Get-Command tailscale.exe -ErrorAction SilentlyContinue
$tailscale=if ($client) { $client.Source } else { Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe' }
if (!(Test-Path -LiteralPath $tailscale)) {
 throw 'Install official Tailscale first: winget install --exact --id Tailscale.Tailscale --source winget . Then sign in using its Windows app and rerun this helper.'
}
function Read-TailscaleJson([string]$Arguments) {
 $probe=New-Object System.Diagnostics.Process
 $probe.StartInfo.FileName=$tailscale
 $probe.StartInfo.Arguments=$Arguments
 $probe.StartInfo.UseShellExecute=$false
 $probe.StartInfo.CreateNoWindow=$true
 $probe.StartInfo.RedirectStandardOutput=$true
 $probe.StartInfo.RedirectStandardError=$true
 try {
  [void]$probe.Start()
  $output=$probe.StandardOutput.ReadToEnd()
  [void]$probe.StandardError.ReadToEnd()
  $probe.WaitForExit()
  if ($probe.ExitCode -ne 0) { throw 'Tailscale query failed. Open the Tailscale app and check its login/connection.' }
  return ($output | ConvertFrom-Json)
 } finally { $probe.Dispose() }
}
try {
 $health=Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 5
 $appState=$health.Content | ConvertFrom-Json
 if ($appState.status -ne 'ok' -or $appState.live_execution -ne $false) { throw 'Unexpected local application' }
} catch { throw "Start ForexLab first and check its local dashboard on port $Port. This helper did not change network settings." }
$status=Read-TailscaleJson 'status --json'
if ($status.BackendState -ne 'Running') { throw 'Sign in and connect using the Windows Tailscale app, then rerun this helper.' }
$dns=([string]$status.Self.DNSName).TrimEnd('.')
if ($dns -notmatch '^[A-Za-z0-9.-]+\.ts\.net$') { throw 'A valid Tailscale HTTPS device name is unavailable; check MagicDNS and HTTPS settings in your tailnet.' }
$config=Read-TailscaleJson 'serve status --json'
if ($config.AllowFunnel) {
 $publicRoutes=@($config.AllowFunnel.PSObject.Properties | Where-Object { $_.Value -eq $true })
 if ($publicRoutes.Count -gt 0) { throw 'Existing public Funnel access was detected and preserved. Disable/review it separately before creating a private phone route.' }
}
$web=@(); $tcp=@()
if ($config.Web) { $web=@($config.Web.PSObject.Properties) }
if ($config.TCP) { $tcp=@($config.TCP.PSObject.Properties) }
$target="http://127.0.0.1:$Port"
if ($web.Count -gt 0 -or $tcp.Count -gt 0 -or $config.Foreground -or $config.Services) {
 $expected=$false
 if ($web.Count -eq 1 -and $tcp.Count -eq 1 -and $web[0].Name -eq ($dns+':443') -and $tcp[0].Name -eq '443' -and $tcp[0].Value.HTTPS -eq $true) {
  $handlers=@($web[0].Value.Handlers.PSObject.Properties)
  $expected=$handlers.Count -eq 1 -and $handlers[0].Name -eq '/' -and $handlers[0].Value.Proxy -eq $target
 }
 if (!$expected) { throw 'An existing Tailscale Serve configuration is present and was preserved. Inspect tailscale serve status before changing it; this helper will not replace another service.' }
 Write-Host 'The matching private ForexLab route already exists; no network change was needed.'
} else {
 Write-Host 'Creating a private tailnet HTTPS route. This does not enable public Funnel access.'
 & $tailscale serve --bg --https=443 $target
 if ($LASTEXITCODE -ne 0) { throw 'Tailscale Serve did not complete. Follow its displayed HTTPS/permission instructions, then rerun. No public port was opened by this helper.' }
}
Write-Host ''
Write-Host "PHONE ADDRESS: https://$dns/"
Write-Host 'On your phone: connect Tailscale to the same private network, open that HTTPS address, then enter the ForexLab session token privately.'
Write-Host 'Android Chrome: menu > Add to Home screen. iPhone Safari: Share > Add to Home Screen.'
Write-Host 'Keep the Windows PC, MT5 and ForexLab server running. The phone does not execute MT5 itself.'
Write-Host 'To stop only this HTTPS route later: tailscale serve --https=443 off (inspect serve status first).'
