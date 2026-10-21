# Validation and acceptance status

Software checks and evidence supplied by the user are recorded separately. Fixture prices and fake broker responses never establish Exness execution or profitability.

## Current Linux verification — October 21, 2026

- Pinned Python development dependencies, including the optional isolated ML stack, install in the Python 3.12 virtual environment. The official MT5 package is Windows-only and is correctly excluded here.
- All **320 backend tests** pass. Coverage includes strategy causality, risk caps, minimum-lot skip, broker/account changes, persistent ambiguous submissions, account-scoped fill/exit attribution, restart migrations, protection alerts, calendar gates, read-only observations, research provenance/jobs, chronological evaluation, purged ML comparisons and isolated customer authorization. One dependency deprecation warning remains; there are no skipped tests.
- Regression checks prevent partial fills from different broker orders being merged across recovery polls, preserve the updated equity risk budget, and stop automation when its consented demo account changes. Missing open-position/exit proof or widened/missing stops activate the entry emergency stop; the code never closes broker positions automatically.
- All **10 frontend numerical/provenance/cost checks** and the production TypeScript/Vite build pass. Browser checks cover four mobile tabs, external-CSV acknowledgement, fixture rejection, explicit costs, isolated ML report metrics/download, pending-order/ledger rendering, selected-symbol calendar gating and 320/390/844 px layouts. Mock browser scenarios are software checks only.
- The tested installation script completed end to end. The running built app passed authenticated status/candle/analysis/research checks and actual queued strategy/ML report generation on generated, explicitly unverified CSV data. The ML fixture fit a model but did not promote it. Mobile browser report display/download, tabs, width checks and token reset passed against this running API with zero JavaScript errors. No broker orders were sent.
- Existing chart/indicator/drawing checks include closed candles, broker precision, SMA/EMA/Bollinger/Wilder RSI/MACD, independent settings, drawing persistence/undo, recoverable exact-symbol history errors and clearing the session token on reload. The corner logo is hidden through the library setting and required textual attribution remains visible.
- The manifest and home-screen icons are served. No service worker caches authenticated API responses or market prices.
- The independent customer portal is tested for tenant isolation, expiry/revocation, seats, enrollment, secret hashing and browser cleanup. It is a metadata service with manually issued licenses; it does not enforce local trading licenses or process payments.

## Evidence supplied from the user's Windows PC

- Screenshots show installation, a running localhost dashboard and an initial 61-test run.
- The October 17 screenshots show an Exness DEMO connection, terminal checks 3/3 and historical-chart checks 7/7 for the selected broker symbol. This confirms connection/history for that version.
- Those screenshots also show equity/free margin 0.00, disabled Algo Trading and stale quotes while the market was closed. They do not establish that execution prerequisites later passed.
- Tailscale devices and Serve readiness were shown. An authenticated dashboard on the physical phone, Android home-screen installation and iPhone acceptance remain unverified.

## Not executed or still missing

- New PowerShell helpers and upgraded execution/research features have not been run on the physical Windows PC from this Linux environment. No Windows task, firewall rule, MT5 permission or Tailscale route was changed by cloud commands.
- No actual demo broker order, protective SL/TP behavior, broker retcode/history propagation, terminal restart/reconnection or recovery result has been verified. Fake-broker tests do not replace those checks.
- No actual Exness dataset or market-performance report has been supplied. Reports produced from generated fixtures or an explicitly unverified external CSV are engine/UI checks only. The older `reports/synthetic-engine-check.json` is not market evidence.
- No four-day or longer real demo observation has been completed. The collector records actual measured intervals and gaps; requesting 96 hours does not create 96 hours of evidence.
- No economic-calendar provider/ingestion adapter is configured. Manual review is the default and expires after at most 15 minutes. Optional calendar-file mode fails closed on missing, stale, malformed or insufficient coverage and cannot be manually overridden.
- Research currently supports linear USD-profit instruments in USD accounts. Constant costs, UTC H4/D1 aggregation and bar-close floating equity omit broker session/DST parity, tick order, intrabar drawdown, variable costs, margin/stop-outs and exact swap schedules. `live_strategy_parity_validated` stays false.
- The ML module is an isolated fixed-horizon long forecasting experiment, not the strategy's SL/TP outcome. It never enters the execution path or promotes a model automatically. Single-class/undersized training windows abstain.
- Billing, local license enforcement, a PostgreSQL multi-user deployment, production capacity/security review and legal/broker release requirements remain outstanding. The private one-terminal trading backend must not be shared as customer isolation.
- Real-money execution remains unavailable. No strategy, ICT/SMC rule, AI score or short demo period guarantees profit or loss-free trading.

## Repeatable verification and next acceptance

Run `bash scripts/install-cloud.sh` for the pinned cloud setup, numerical frontend checks, production build and Python suite. Start the synthetic-only cloud backend with `bash scripts/start-cloud.sh`; verify `/health`, authenticated status/candles/analysis and the built dashboard internally. Cloud localhost is not a user-facing preview.

On Windows, update the existing checkout and restart analysis. Follow [research](RESEARCH.md) to export real history and enter actual broker cost assumptions, then [acceptance](ACCEPTANCE.md) for funded DEMO permissions, valid signals, broker fills/protection/recovery, physical mobile checks and measured observation. Do not force a trade or remove a pending lock to produce a result. Read [deployment](DEPLOYMENT.md) before optional logon startup and [commercial scope](COMMERCIAL.md) before planning public distribution.

Source and uploaded originals stay in the repository; private databases, tokens, CSVs and personal reports belong under ignored `runtime/`. GitHub publication, saved cloud configuration, environment publication and restoration in a new task are separate outcomes. Cloud configuration saving does not publish or prove fresh-task restoration, and cloud access does not grant access to the user's C: drive.
