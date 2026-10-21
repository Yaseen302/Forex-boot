# Windows 11 + Exness MT5 setup — Roman Urdu guide

Yeh guide aapke apne Windows PC ke liye hai. Cloud assistant aapke C: drive ko access nahi kar sakta aur aapke PC par software install hone ka daawa nahi karta.

Agar Git/Python/Node aur ForexLab pehle se installed hain, dobara install na karein: neeche **Update the existing installation** follow karein. October 17 screenshots ne dashboard, MT5 demo connection aur history confirm ki thi; later features ka Windows acceptance alag baqi hai.

## 1. Software install karein

1. Microsoft Store/App Installer se `winget` available hona chahiye. Windows Terminal mein neeche commands aik aik karke chalayein. Installer agar UAC poochay to usay apne PC par review karein.

```powershell
winget install --exact --id Python.Python.3.11 --source winget
winget install --exact --id OpenJS.NodeJS.LTS --source winget
winget install --exact --id Git.Git --source winget
```

Agar winget nahi hai to Python 3.11 **Windows x64** python.org se, Node.js LTS nodejs.org se aur Git git-scm.com se install karein. Installer signatures/publisher check karein. Python installer mein Python launcher aur PATH options select karein. ARM/32-bit Python use na karein. Install ke baad Terminal close karke dobara kholein.

2. Aapka broker **Exness** hai. Exness Personal Area ki official platform/download screen se MT5 Windows installer lein. Apne demo trading account ki details mein **MT5** platform aur exact demo server check karein; doosray account ka server guess na karein. Apne broker ki official site se **MetaTrader 5 desktop** install karein. MT4 ya sirf mobile MT5 is bridge ke liye kaafi nahi. Generic MT5 official site: https://www.metatrader5.com/en/download . Broker installer sahi demo server provide kar sakta hai.
3. MT5 mein demo account login karein. Password MT5 mein rahe; code, chat, dashboard ya GitHub mein na dein.
4. Exness ke account type ke mutabiq symbol suffix badal sakta hai. `EURUSDm` ko hardcode na karein. Market Watch mein exact broker symbol dekhein: `EURUSD`, `EURUSDm`, etc. Bot broker ki list dikhata hai, suffix guess nahi karta.
5. EURUSD ke D1, H4, M30 charts kholein aur history load hone dein. Export ke liye MT5 Options > Charts mein enough "Max bars in chart" set karein. Laptop sleep band rakhein jab demo session chal raha ho.

## 2. Project setup

Project ZIP `C:\ForexLab` mein extract karein, ya repository mein code upload hone ke baad apni repository clone karein. Repository: https://github.com/Yaseen302/Forex-boot . `scripts/bootstrap-windows.ps1` installs missing Git/Python/Node tools, clones into your user folder by default, runs setup and starts the synthetic dashboard. Existing files are preserved. You can also clone manually after Git is installed.

```powershell
cd C:\ForexLab
py -3.11 --version
node --version
npm.cmd --version
powershell -ExecutionPolicy Bypass -File .\scripts\setup-windows.ps1
```

`ExecutionPolicy Bypass` sirf is invocation par apply hota hai; machine policy permanently nahi badalta. Corporate policy block kare to apne administrator se baat karein. Setup script dependency install, dashboard build aur automated tests chalata hai. `reference/` ke purane Streamlit scripts new entry point nahi hain.

## 3. Pehle synthetic, phir MT5 analysis

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-windows.ps1
```

Script jo local address aur session token dikhaye, apne browser mein use karein. Synthetic banner ko broker connection na samjhein. Ctrl+C se server rok sakte hain.

MT5 data ke liye:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-windows.ps1 -Source mt5
```

Dashboard par account, equity, broker symbols aur D1/H4/M30 data check karein. Last closed candle aur broker chart compare karein. Login token har restart par badalta hai; page reload par token memory se clear hota hai.

## 4. Demo orders — explicit opt-in

Read-only checks ke baad:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-windows.ps1 -Source mt5 -EnableDemo
```

MT5 mein Tools > Options > Expert Advisors ke under algorithmic trading permissions check karein. Agar "Disable automated trading through the external Python API" enabled ho to demo execution ke liye usay uncheck karna par sakta hai; sirf read-only data ke liye is permission ko badalne ki zaroorat nahi. MT5 terminal aur broker account ki automated/expert trading permissions check karein. Broker-confirmed **demo** account zaroori hai; real account ko code reject karega. Sahi broker symbol select karein. Default manual mode mein economic calendar khud review karein, phir 15-minute clearance button use karein; expiry par new entry band rehti hai. Optional provider-file calendar gate ke liye [NEWS.md](NEWS.md) follow karein. Provider downloader/credentials yahan configured nahi hain.

- "Evaluate & submit one demo order" server par analysis aur saare checks dobara karta hai. `WAIT` ya minimum-lot risk failure par trade force na karein.
- "Enable demo automation" har 30 seconds check karta hai. News clearance expire hone, emergency, disagreement ya risk failure par trade nahi karta. App restart par automation OFF ho jati hai.
- Emergency stop sirf **nayi entries** rokta hai. Existing broker positions close nahi karta; SL/TP broker par rehte hain. Existing positions ko MT5 mein monitor/manage karein.
- $10 balance par 0.25% sirf $0.025 risk hai. Broker minimum lot aksar is se zyada risk karega, is liye **skip** sahi outcome hai.

Agar timeout/unknown submission aaye to retry ya database delete na karein. MT5 Trade aur History tabs inspect karein. `GET /api/orders` aur SQLite ledger ka backup rakhein. Pending record automatic retry block karta hai. Trade view mein **Sync broker history** read-only reconciliation chalata hai. Exact account/correlation/history match par hi resolution hota hai; missing history ya partial/uncertain fill lock rehta hai. Ye button retry ya manual unlock nahi karta. Broker ke actual position, SL/TP aur fill ko inspect karein.

## 5. Four-day demo observation

Har din connection, stale history, symbol/lot specs, risk skips, spread, broker rejections, duplicate prevention, server restart, emergency stop aur actual MT5 deal/SL/TP inspect karein. News clearance ki expiry test karein. Daily equity baseline app ke first observation se banti hai; app band rehne ke dauran equity changes reconstruct nahi hote. Weekend ko no-trade expected ho sakta hai.

Four days ke results ko long-term profitability ka saboot ya commercial launch approval na samjhein. Alag market conditions, broker history par cost-aware OOS tests aur lambi demo monitoring chahiye.

## 6. Mobile / VPS

Pehle local Windows workflow verify karein. Backend default sirf loopback par sunta hai. Phone access ke liye Tailscale ka supported private route ya authenticated HTTPS tunnel configure karein; raw port forward na karein. Backend bearer token har private API endpoint par zaroori hai. Tailscale/Cloudflare, Windows VPS, domain/SSL is delivery mein install/configure nahi kiye gaye. Private mobile setup ka optional helper aur Android/iPhone instructions ab docs/MOBILE.md mein diye hain; unhein aapke devices par chalana aur verify karna baqi hai. Multi-user public hosting is single-account prototype ka supported mode nahi.

## Updated mobile terminal and Exness connection checks

The updated terminal has mobile Charts / Analysis / Trade / Journal navigation. Indicator settings include independently configurable EMA, SMA, Bollinger Bands, Wilder RSI and MACD. They describe completed candles; they do not bypass server-side strategy/risk rules. The small chart-corner logo is disabled using the library's supported option; visible footer attribution remains.

Your earlier screenshots showed installation/build/tests on Windows and subsequently a broker-confirmed DEMO connection with terminal/history checks passing. That verifies those checks at that time, not order execution. The same screenshot showed 0.00 equity/free margin and disabled Algo Trading; current virtual funding/permissions and later updates still need verification. The cloud cannot inspect your Windows session.

### Update the existing installation

First press **Ctrl+C in the old server window**. Open Windows PowerShell (the prompt begins `PS`, not bare CMD). From the existing project:

```powershell
Set-Location (Join-Path $env:USERPROFILE 'ForexLab')
git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) { throw 'Update failed; send the error before continuing.' }
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\update-windows.ps1 -Source mt5
```

The update script preserves local changes, tests Python/indicators, builds the terminal and starts **MT5 read-only analysis**. It refuses to run while port 8000 is occupied. Copy the new session token into the login screen; then Ctrl+F5 in the browser if an old layout remains. On Windows you can subsequently double-click `ForexLab.cmd` to choose preview, MT5 analysis, read-only connection test or explicit demo-control startup.

Normal Windows accounts can deny symbolic-link creation with `WinError 1314`. Two native filesystem integration tests report an explicit **SKIPPED** reason in that case; this does not require changing Windows permissions. ID/path restrictions and the remaining checks still run, and every unexpected test failure still stops setup. These skipped checks are not reported as passes. Linux or a Windows account with symlink support runs them normally.

### Read-only broker preflight

Keep Exness desktop MT5 open with the demo account logged in. Use the exact name from Market Watch. In the Trade view use **Check MT5 connection**, or in a separate terminal run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-mt5.ps1 -Symbol EURUSDm
```

`EURUSDm` is only an example: if your account lists `EURUSD` or another suffix, select that exact symbol. The checker suggests available matches but does not change broker symbols or select an account. Multiple terminal installations can be disambiguated with `-TerminalPath 'C:\Program Files\Your Broker MT5\terminal64.exe'` for the checker/start script.

Report meanings: `connected` only means the terminal is online; `ready_for_data` means its data prerequisites pass; `ready_for_demo` adds demo account, permissions, current quote/history/spread, empty account exposure and adapter compatibility. Passing preflight is not an entry signal, risk approval or proof of profits. The CLI exits successfully for data readiness, so inspect the separate demo-readiness result before enabling orders.

Show the exact symbol in Market Watch and open D1/H4/M30 charts to load history. Enable Algo Trading/external Python API permissions only when evaluating demo execution. The current adapter supports **FOK only**; a broker symbol that only supports IOC/RETURN is reported as unsupported rather than submitting an incompatible request.

On weekends the FX market can be closed: history may display correctly while stale quotes block entries. The M30 strategy only permits new entries in the first five minutes after a completed candle; outside that interval preflight can legitimately show not ready for demo.

### Enable automatic demo entries only after inspecting the report

Stop the read-only app with Ctrl+C, then:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-windows.ps1 -Source mt5 -EnableDemo
```

Select the exact broker symbol, inspect account/demo mode and connection checks, review the economic calendar yourself, grant a 15-minute news clearance and explicitly enable demo automation. The worker checks every 30 seconds, enters only on aligned fresh D1/H4/M30 signals, and never forces a trade to pass a test. Existing positions or a small-account minimum-lot conflict block new entries. Automation resets OFF on restart. No order is sent just by updating or running the connection checker.

The mobile layout works at phone widths. A phone's own localhost is a different machine: actual phone access to the Windows backend still needs a private authenticated HTTPS route such as Tailscale Serve; that network deployment is not installed by this update. The optional scripts/enable-mobile.ps1 helper and docs/MOBILE.md now guide a private Tailscale Serve setup without opening the raw API port. Do not expose the raw API port publicly.

## Reports, monitoring and next acceptance

After updating, use **Analysis → Research & reports** to export closed M30 broker history, enter explicit costs and run chronological or isolated ML research. No orders are placed by that workflow. See [RESEARCH.md](RESEARCH.md) for exact CSV/specification requirements and command-line examples.

Read-only long-duration observation and private support reports are documented in [ACCEPTANCE.md](ACCEPTANCE.md). Optional analysis-only Task Scheduler setup is in [DEPLOYMENT.md](DEPLOYMENT.md). These scripts have not been run on your actual Windows PC by the cloud; a requested 96-hour session is not a completed four-day test. New orders still require a valid fresh signal, virtual demo equity, broker permissions, news clearance and every risk guard.
