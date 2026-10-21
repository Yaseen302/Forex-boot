# Staged operation and Windows startup

ForexLab currently runs as one Python backend attached to one Windows MT5 terminal and one broker account. The browser is a private dashboard; Android/iPhone do not run the Python MT5 bridge. The Windows PC or Windows VPS must remain on, connected and awake. Use the existing project checkout; cloud tasks already have isolated workspaces and do not need a new Git worktree.

## Stage A: Private analysis

Use `scripts/start-windows.ps1 -Source mt5`. Keep one backend process, `--workers 1`, no reload server and one intended MT5 installation. If more than one terminal exists, explicitly select its `terminal64.exe` with `-TerminalPath`. Read-only connection checks work with available historical data even when the forex market is closed.

Local access remains `http://127.0.0.1:8000`. Private phone access uses the existing Tailscale helper and HTTPS. It does not require a router port-forward, public Funnel, firewall disablement, MT5 password in the website or an API token in a URL. Do not change the server bind address to `0.0.0.0` to troubleshoot a private phone connection.

## Stage B: Supervised demo

After the acceptance prerequisites pass, use the documented explicit demo execution opt-in and enable automation deliberately in the dashboard. The app checks the broker-confirmed demo mode again; startup alone must not enable trading. Keep the configured calendar gate and its limitations visible; see [NEWS.md](NEWS.md). The default manual clearance expires, and optional calendar-file mode needs a real fresh provider feed. Deploying a server does not remove that gate or make the bot an unattended 24/7 system.

Run the read-only collector separately if required. It sends no orders and does not stand in for an order fill/SL/TP check. Follow `ACCEPTANCE.md` for broker and observation evidence. Preserve unresolved broker submissions until reviewed.

## Optional logon startup, reviewed locally

No Windows task or service has been installed by this cloud session. The following is an optional **analysis-only, interactive logon task** to review and execute on the Windows PC after the setup is verified. It needs no stored Windows or broker password and requests no elevated run level. It starts after the user logs on; it is not an unattended boot-time service.

First stop the existing backend with Ctrl+C and test this launcher manually. Keep MT5 open:

```powershell
$project = Join-Path $env:USERPROFILE 'ForexLab'
powershell -NoProfile -ExecutionPolicy RemoteSigned -File "$project\scripts\startup-analysis.ps1"
```

The wrapper refuses a listening port 8000 and uses a per-session mutex. The backend already uses one worker; the task's `IgnoreNew` policy prevents another scheduled instance. Always use one launcher, and do not start a second manual backend alongside the task. The wrapper never stops an unrelated process or changes MT5 trading permissions.

Once this manual check passes, stop that server. Review and run the following in PowerShell. An existing task with the same name is preserved and must be inspected separately:

```powershell
$project = Join-Path $env:USERPROFILE 'ForexLab'
$taskName = 'ForexLab-Private-Analysis'
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    throw 'This task already exists; inspect it before making any changes.'
}
$launcher = Join-Path $project 'scripts\startup-analysis.ps1'
if (!(Test-Path -LiteralPath $launcher)) { throw 'Update the project and test startup-analysis.ps1 first.' }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -NoExit -ExecutionPolicy RemoteSigned -File "' + $launcher + '"') -WorkingDirectory $project
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'ForexLab private MT5 analysis; no auto execution, one backend.'
```

The visible server window supplies a new local dashboard token at each launch. Do not redirect that window to a support log or embed the token in the task arguments. If the intended MT5 terminal requires a specific path, review/edit the action's explicit `-TerminalPath` argument. Do not store the broker password in a script/task.

Test with `Start-ScheduledTask -TaskName 'ForexLab-Private-Analysis'` only when no server is already running. Verify localhost, the demo account, connection checks and the private phone address. Test a real logout/login or reboot separately. Startup can legitimately report disconnected until the user has opened and authenticated the intended MT5 terminal; it does not bypass that step. Confirm automation is off.

To stop using the optional task:

```powershell
Disable-ScheduledTask -TaskName 'ForexLab-Private-Analysis'
```

Then stop the visible server with Ctrl+C. Disabling the trigger alone does not close an already running backend or broker positions. To remove the reviewed task later:

```powershell
Unregister-ScheduledTask -TaskName 'ForexLab-Private-Analysis' -Confirm
```

## Restart, updates and recovery

1. Disable demo automation, inspect open positions in MT5 and preserve any ambiguous submissions. Emergency stop only blocks new entries.
2. Stop the single server. Back up the application trading database and observation database privately. Both may contain sensitive operational data; do not upload them to GitHub or support chat.
3. Apply a pinned reviewed source update with the repository helper, frozen dependency installs, automated checks and frontend build. Do not overwrite `.env` or local user files.
4. Restart in MT5 analysis mode, obtain the new session token and verify account identity, balances, quote freshness, history, risk configuration and reconciliation. Keep automation off until manually reviewed.
5. If a migration/update fails, restore the known matching code/dependencies/database backup together. Do not delete journals, uncertain order locks or observation failures to make a check pass.

The observer persists the same salted account identity across process sessions. It excludes restart gaps from measured elapsed coverage. Account switches, invalid readings and clock problems remain visible. Its support exporter allowlists summary fields; it never dumps process environment, API tokens, broker credentials, raw order/event payloads or terminal filesystem paths.

## Stage C: Customer/public deployment remains a separate project gate

A Windows VPS can host the same private demo workflow after actual VPS/MT5 acceptance tests. Do not treat that as a commercial multi-user service. The current shared backend/account model and one session token must not be reused as customer isolation.

A separate customer/license/device control-plane prototype is described in [COMMERCIAL.md](COMMERCIAL.md). It neither shares broker credentials nor replaces trading-account isolation. Before public distribution, review actual deployment authorization, tenant/account isolation, secret handling, per-user audit/access controls, database migration/backup/restore, monitoring and incident response, packaging/update trust, billing and broker/regulatory requirements. Set retention and deletion policies for personal trading history. Load/security tests and actual Android/iPhone acceptance also remain necessary. Public deployment and real-money execution are not enabled by these instructions. Neither a successful launch nor a demo report guarantees profit.
