# Phone access, home-screen installation and weekend onboarding

ForexLab is a mobile web terminal connected to a Windows MT5 bridge. It is not the native MetaTrader5 app. The phone can show charts, history, indicators, account/positions, connection checks and demo controls. The Windows PC or Windows VPS runs MT5 and the bot, including when the phone is locked. Keep the computer powered on and the server/MT5 connected.

## Saturday: connect first, trade later

You can connect MT5, verify the demo account, read available historical candles, test indicators, drawings and the interface on Saturday. Terminal connectivity, historical-data readiness and permission for a new order are different states. Broker history still has to exist locally; open the exact instrument's D1/H4/M30 charts in the desktop terminal if needed.

A stale bid/ask quote is consistent with a closed market or paused feed. It does **not** prove either a disconnection or a particular broker session schedule. The connection guide keeps these states separate. When the FX market is closed, no order is forced as a test. The execution engine keeps quote-age, entry-window, spread, demo account and risk guards intact.

Start today with read-only broker analysis:

```powershell
Set-Location (Join-Path $env:USERPROFILE 'ForexLab')
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-windows.ps1 -Source mt5
```

Open the dashboard on this PC, enter the session token, select the exact broker symbol, then use **Trade → Run MT5 connection checks**. The guide shows terminal connection, historical data and new-entry readiness independently. A connected demo account with history and stale quotes is an acceptable weekend data/phone setup result, **not** approval to trade.

## Private phone access with Tailscale Serve

Phone localhost points to the phone itself. A PC address printed as `127.0.0.1` cannot be copied to a phone to reach the PC. Use an authenticated private HTTPS route; the backend can remain bound to loopback.

1. Keep the ForexLab server running on the Windows PC. Open a **second** PowerShell window.
2. Install official Tailscale on Windows, if it is not already installed:

```powershell
winget install --exact --id Tailscale.Tailscale --source winget
```

3. Open the Windows Tailscale app and sign in. Install Tailscale from the official Android/iPhone app store on the phone and connect it to the same private network. Follow your tailnet access policy and device approval requirements.
4. In the second PC PowerShell window run:

```powershell
Set-Location (Join-Path $env:USERPROFILE 'ForexLab')
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\enable-mobile.ps1
```

The helper checks local app health and Tailscale login, then uses **Tailscale Serve**, not Funnel, to proxy private HTTPS to `http://127.0.0.1:8000`. Serve may require tailnet HTTPS/certificate enablement; follow Tailscale's instructions in your account. The helper preserves unrelated existing Serve configuration and does not change Windows firewall rules or install a VPN inside the cloud environment. Re-running the helper recognizes an identical existing route.

5. Open the **PHONE ADDRESS** printed by the helper, such as `https://your-device.your-tailnet.ts.net/`, on the connected phone. This is an example shape, not an actual address. Enter the current ForexLab session token privately. Tokens change when the Windows launcher restarts; no broker password is entered on the phone.
6. Android Chrome: menu → **Add to Home screen / Install app**. iPhone Safari: Share → **Add to Home Screen**. The terminal includes a manifest and icons and opens in standalone mode when supported. A direct Install button appears only when the browser offers it; this button cannot force browser/OS support.

The web app deliberately has no service worker caching authenticated API responses or market prices. It needs network access; home-screen installation does not make trading work offline. Phone installation, Tailscale device login and the actual private HTTPS route need to be verified on the real PC and phone; cloud browser tests cannot establish that deployment.

To stop a configured Serve route, inspect `tailscale serve status` and disable the relevant HTTPS route. Do not reset an unknown Serve configuration or enable public Funnel to make setup easier.

## A short walkthrough to teach another person

1. Install MT5 and ForexLab on **their own Windows PC/VPS**.
2. Log in to their demo account inside MT5. Credentials stay in MT5.
3. Start read-only analysis, select the exact broker symbol and run connection checks.
4. Verify historical charts and indicators, including when the market is closed. Understand why new entries remain blocked.
5. Configure their private phone route and add the web terminal to the home screen.
6. During an open broker session, inspect current quote/history and all remaining readiness issues. Demo automation is a separate explicit opt-in and still needs the configured news gate (expiring manual economic-calendar review by default).

This is one account per backend, not a customer account-sharing platform. Giving several customers access to one running instance would expose the same account and controls. A separate license/device control-plane prototype is documented in [COMMERCIAL.md](COMMERCIAL.md); it does not isolate this shared trading backend or make it a public customer platform. Four demo days do not prove profitability, and no strategy guarantees profits or zero losses.
