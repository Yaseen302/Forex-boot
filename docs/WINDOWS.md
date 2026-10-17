# Windows 11 + Exness MT5 setup — Roman Urdu guide

Yeh guide aapke apne Windows PC ke liye hai. Cloud assistant aapke C: drive ko access nahi kar sakta aur aapke PC par software install hone ka daawa nahi karta.

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

MT5 mein Tools > Options > Expert Advisors ke under algorithmic trading permissions check karein. Agar "Disable automated trading through the external Python API" enabled ho to demo execution ke liye usay uncheck karna par sakta hai; sirf read-only data ke liye is permission ko badalne ki zaroorat nahi. MT5 terminal aur broker account ki automated/expert trading permissions check karein. Broker-confirmed **demo** account zaroori hai; real account ko code reject karega. Sahi broker symbol select karein. Economic calendar khud review karein, phir 15-minute clearance button use karein. Is version mein automatic news provider nahi hai; clearance expire ho to koi nayi entry nahi hoti.

- "Evaluate & submit one demo order" server par analysis aur saare checks dobara karta hai. `WAIT` ya minimum-lot risk failure par trade force na karein.
- "Enable demo automation" har 30 seconds check karta hai. News clearance expire hone, emergency, disagreement ya risk failure par trade nahi karta. App restart par automation OFF ho jati hai.
- Emergency stop sirf **nayi entries** rokta hai. Existing broker positions close nahi karta; SL/TP broker par rehte hain. Existing positions ko MT5 mein monitor/manage karein.
- $10 balance par 0.25% sirf $0.025 risk hai. Broker minimum lot aksar is se zyada risk karega, is liye **skip** sahi outcome hai.

Agar timeout/unknown submission aaye to retry ya database delete na karein. MT5 Trade aur History tabs inspect karein. `GET /api/orders` aur SQLite ledger ka backup rakhein. Pending record automatic retry block karta hai. Broker history ko local signal se match karke developer reconciliation karna baqi manual operation hai; UI unlock button nahi diya gaya.

## 5. Four-day demo observation

Har din connection, stale history, symbol/lot specs, risk skips, spread, broker rejections, duplicate prevention, server restart, emergency stop aur actual MT5 deal/SL/TP inspect karein. News clearance ki expiry test karein. Daily equity baseline app ke first observation se banti hai; app band rehne ke dauran equity changes reconstruct nahi hote. Weekend ko no-trade expected ho sakta hai.

Four days ke results ko long-term profitability ka saboot ya commercial launch approval na samjhein. Alag market conditions, broker history par cost-aware OOS tests aur lambi demo monitoring chahiye.

## 6. Mobile / VPS

Pehle local Windows workflow verify karein. Backend default sirf loopback par sunta hai. Phone access ke liye Tailscale ka supported private route ya authenticated HTTPS tunnel configure karein; raw port forward na karein. Backend bearer token har private API endpoint par zaroori hai. Tailscale/Cloudflare, Windows VPS, domain/SSL is delivery mein install/configure nahi kiye gaye. Multi-user public hosting is single-account prototype ka supported mode nahi.
