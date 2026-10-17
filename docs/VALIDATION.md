# Validation and acceptance status

## Verified in this Linux cloud instance

- Python 3.12 virtual environment installation, pinned Python package installation and repeatable npm lockfile installation.
- 61 automated tests: risk caps, invalid inputs, non-decimal lot steps, small-account skip, daily loss/drawdown, position/spread/margin/news/stale-quote/emergency guards, all timeframe fixture analysis, pivot confirmation, FVG mitigation, candle validation, persistent duplicates/pending orders, account anchors, authenticated API, no live endpoint, demo-account rejection of live, submission ambiguity and broker-deal verification using fakes, automation idle/failure handling, and backtest signal timing/stop-first costs.
- Production TypeScript/Vite build.
- Headless Chromium desktop (1440 px) and mobile (390 px): login, candle chart, timeframe switching, indicator controls, price/time rectangle drawing with local persistence, emergency entry stop and release, mobile layout without horizontal overflow, token cleared on browser reload. Browser errors: none on final check.
- Running FastAPI serves the built dashboard and authenticated market-analysis requests. Synthetic prices are clearly labelled.
- 8,200 synthetic M30 candles processed through the backtest and chronological/rolling evaluator. `reports/synthetic-engine-check.json` is an engine-check report, **not** a market-performance report. A synthetic trade or no-trade period does not establish a profitable strategy.
- Official MetaTrader5 5.0.5488 CPython 3.11 Windows x64 wheel is available from PyPI. It is not runnable in this Linux cloud.
- Final npm audit: 0 reported vulnerabilities at validation time, including development packages. This is a package-advisory check, not a security certification.

## Not executed / external prerequisites

- Windows PowerShell setup/start scripts, installation on the user's physical Windows 11 PC and Exness desktop MT5 connection have not been executed here. The scripts and tailored instructions are supplied for that machine.
- Broker account permissions, real contract/tick/volume specs, terminal restarts/reconnection, actual demo orders, live broker retcodes/deal-history propagation and broker SL/TP behavior need Windows/Exness acceptance testing. Mock tests do not establish these work with Exness.
- No real broker history or economic-calendar feed was provided. There is no real-price backtest, profitability evidence, statistical significance assessment or four-day demo observation yet. The computer and MT5 must remain running during demo monitoring.
- Fixed UTC OHLC resampling, constant costs and closed-equity drawdown are research approximations, not a broker-accurate tick simulator. See `RULES.md` before interpreting reports.
- Automated MT5 reconnection uses initialize and connection checks per operation; actual terminal-restart tests remain unrun. Uncertain orders intentionally require manual broker-history reconciliation and block all later submissions.

## Remaining product work

- Validate broker execution and long-term strategy behavior on real history across market regimes. Refine entry definitions only with held-out evaluation.
- Integrate and test a real news/session calendar before unattended extended operation; manual clearances last at most 15 minutes.
- General multi-currency backtesting, intratrade equity/margin simulation, broker calendar alignment and accurate variable spread/swap modelling.
- Additional discretionary ICT/SMC concepts, historical order-block lifecycles, equal-high/low pools, optional M5/M15 confirmation, more indicators and richer drawing editing.
- ML probability model with purged chronological splits, calibration and walk-forward baseline comparison, **after** the fixed strategy is validated. No ML model is trained or used by this implementation.
- Multi-user/account isolation, licensing/subscriptions, PostgreSQL migration, authenticated production deployment and commercial/legal review.
- Real-money execution is deliberately unavailable. Four demo days cannot justify an automatic live/public launch.

## Delivery boundaries

Source is in `/workspace/Forex-boot`; uploaded originals are preserved under `reference/`. GitHub publication is a separate operation from local validation. No changes were made to the user's C: drive from this cloud session. The source archive excludes tokens, databases, dependency directories and generated personal configuration. Cloud setup instructions do not demonstrate a published snapshot or a successful fresh-task restoration.

Cloud configuration draft: `install_script` and `start_skill` were saved. The running server was restarted and checked through authenticated status/candle/analysis requests. Draft saving does not publish a snapshot. Review and save in environment settings, then publish if you want to retain this cloud setup for future tasks.
