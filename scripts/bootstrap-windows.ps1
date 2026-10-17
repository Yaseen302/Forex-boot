param([string]$ProjectPath=(Join-Path $env:USERPROFILE 'ForexLab'),[ValidateSet('synthetic','mt5')][string]$Source='synthetic')
$ErrorActionPreference='Stop'
if (Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue) {
 throw 'ForexLab port 8000 is already in use. Press Ctrl+C in the previous server window before running setup/update. No process was stopped.'
}
if (!(Get-Command winget.exe -ErrorAction SilentlyContinue)) {
 throw 'winget is unavailable. Install Microsoft App Installer from Microsoft Store, reopen PowerShell and run again.'
}
function Refresh-Path {
 $env:Path=[Environment]::GetEnvironmentVariable('Path','Machine')+';'+[Environment]::GetEnvironmentVariable('Path','User')
}
function Install-Tool([string]$Id) {
 Write-Host "Installing $Id using the official winget catalog..."
 & winget.exe install --exact --id $Id --source winget --accept-package-agreements --accept-source-agreements
 if ($LASTEXITCODE -notin @(0,3010,-1978335189)) { throw "Installation failed for $Id (exit $LASTEXITCODE). Send this error; do not keep retrying blindly." }
 Refresh-Path
}
function Test-Python311 {
 $launcher=Get-Command py.exe -ErrorAction SilentlyContinue
 if (!$launcher) { return $false }
 # Windows PowerShell 5.1 can turn redirected native stderr into a terminating
 # NativeCommandError. Probe through Process so missing Python is a normal false.
 $probe=New-Object System.Diagnostics.Process
 $probe.StartInfo.FileName=$launcher.Source
 $probe.StartInfo.Arguments='-3.11 --version'
 $probe.StartInfo.UseShellExecute=$false
 $probe.StartInfo.CreateNoWindow=$true
 $probe.StartInfo.RedirectStandardOutput=$true
 $probe.StartInfo.RedirectStandardError=$true
 try {
  [void]$probe.Start()
  $stdout=$probe.StandardOutput.ReadToEnd()
  $stderr=$probe.StandardError.ReadToEnd()
  $probe.WaitForExit()
  return ($probe.ExitCode -eq 0 -and ($stdout+$stderr) -match 'Python 3\.11\.')
 } catch { return $false } finally { $probe.Dispose() }
}
if (!(Get-Command git.exe -ErrorAction SilentlyContinue)) { Install-Tool 'Git.Git' }
if (!(Test-Python311)) { Install-Tool 'Python.Python.3.11' }
if (!(Get-Command node.exe -ErrorAction SilentlyContinue)) { Install-Tool 'OpenJS.NodeJS.LTS' }
Refresh-Path
if (!(Get-Command git.exe -ErrorAction SilentlyContinue)) { throw 'Git installation requires reopening PowerShell; reopen and rerun this script.' }
if (!(Get-Command py.exe -ErrorAction SilentlyContinue)) { throw 'Python launcher requires reopening PowerShell; reopen and rerun this script.' }
if (!(Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw 'Node.js requires reopening PowerShell; reopen and rerun this script.' }
if (!(Test-Python311)) { throw 'Python 3.11 is not available; reopen PowerShell after installation and rerun this script.' }
& py -3.11 --version
if (Test-Path $ProjectPath) {
 if (!(Test-Path (Join-Path $ProjectPath '.git'))) { throw "Folder $ProjectPath already exists and is not a Git checkout. It was preserved. Choose another -ProjectPath." }
 $existingRemote=& git.exe -C $ProjectPath remote get-url origin
 if ($LASTEXITCODE -ne 0 -or $existingRemote.Trim() -notmatch '^https://github\.com/Yaseen302/Forex-boot(?:\.git)?/?$') { throw 'Existing folder has another remote; it was preserved.' }
 $changes=& git.exe -C $ProjectPath status --porcelain
 if ($changes) { throw 'Existing project has local changes. They were preserved; update it manually before proceeding.' }
 & git.exe -C $ProjectPath pull --ff-only origin main
 if ($LASTEXITCODE -ne 0) { throw 'Git update failed. Check repository access and existing branch.' }
} else {
 & git.exe clone --branch main https://github.com/Yaseen302/Forex-boot.git $ProjectPath
 if ($LASTEXITCODE -ne 0) { throw 'Clone failed. For a private repository, sign in to GitHub when Git Credential Manager asks.' }
}
Set-Location $ProjectPath
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ProjectPath 'scripts\setup-windows.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Project setup failed; send the last error shown.' }
Write-Host "Project saved at $ProjectPath. Starting $Source analysis; no broker orders are enabled."
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ProjectPath 'scripts\start-windows.ps1') -Source $Source
