# ForexLab

A local Forex research terminal: Python/FastAPI, React/TypeScript/Tailwind, TradingView Lightweight Charts, SQLite and an official Windows MT5 adapter. The uploaded prototype is preserved unchanged in `reference/` and is not the new application entry point.

**Status: research/demo implementation, not a validated profitable or commercial product. Live execution is unavailable.** No software can promise zero losses or turn $10 into $1,000 safely. Four demo days test connectivity and operations, not profitability.

## Start on Windows

Follow [the Windows guide](docs/WINDOWS.md) for Python 3.11 x64, Node.js LTS and broker MT5. If ForexLab is already installed, update the existing checkout instead of reinstalling software or extracting over it.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup-windows.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\start-windows.ps1
```

The default uses visibly labelled synthetic development prices. The start script generates a session API token; paste it into the dashboard. The browser communicates with FastAPI, never directly with MT5.

With the MT5 terminal running and logged in, use `start-windows.ps1 -Source mt5` for read-only broker analysis. **Orders require a separate opt-in:** `start-windows.ps1 -Source mt5 -EnableDemo`, a broker-confirmed demo account, news/calendar clearance and all risk conditions. Manual review is the default; optional file-based calendar ingestion requires a real, continuously refreshed provider feed. Automation is optional in the dashboard and resets to off after server restart.

## Cloud/Linux development

```bash
bash scripts/install-cloud.sh
bash scripts/start-cloud.sh
```

The backend serves the built frontend on port 8000. The API token is in ignored `runtime/api-token`; do not share it or publish `runtime/`. The Linux cloud can run synthetic research and tests, but cannot connect to Windows MT5 through the official Python package. For frontend hot reload: run `npm run dev` in `frontend/` while the API is running; Vite proxies `/api` to the local backend.

Use the existing checkout; cloud tasks are already isolated. Do not create another Git worktree unless explicitly requested.

## Included

- All 21 official MT5 timeframes, closed-candle charting, independent EMA/SMA/Bollinger/RSI/MACD settings and panels, persistent trendline, Fibonacci and rectangle drawings. Mobile Charts/Analysis/Trade/Journal navigation. The chart corner logo is disabled through supported configuration; attribution remains in the footer.
- Deterministic confirmed pivots, HH/HL and LH/LL trend, BOS/CHoCH candidates, FVG and current-break order-block candidates, liquidity sweeps, support/resistance and aligned D1/H4/M30 entries.
- Decimal lot-step sizing, 0.25% default equity risk, minimum 2R at execution, 2% daily loss/5% drawdown entry stops, one account-wide position/order, spread/stale quote/margin checks and persistent emergency entry stop.
- Explicit demo-only execution through broker `order_check`, FOK `order_send` and deal-history verification. Persistent duplicate and uncertain-submission protection. Read-only broker-history reconciliation keeps uncertain/partial submissions locked and detects protection/risk changes.
- SQLite controls, orders and event journal; session API authentication for all data and control endpoints. Read-only MT5 connection preflight checks exact symbols, contract specifications, terminal/account permissions, quote/history freshness and adapter support.
- M30 broker-history export with contract specifications, SHA-256-bound provenance, explicit-cost backtesting, chronological/rolling reports, and isolated ML forecasting research. Research runs do not enable orders or promote models into execution.
- Read-only demo observation with actual elapsed coverage, failures/recoveries and allowlisted support reports. Separate customer/license/device control-plane prototype; no broker password sharing or trading service in that component.
- No real-price profitability report or completed observation period is supplied; the actual Windows/Exness evidence still has to be collected.

## Test and research

```bash
.venv/bin/python -m pytest -q
cd frontend
npm test
npm run build
```

On Windows use `.venv\Scripts\python.exe` instead. Development setup includes `requirements-ml.txt` for offline research and its tests. Core `requirements.txt` remains independent of scikit-learn. See [the research guide](docs/RESEARCH.md) for the in-app Analysis workflow, complete cost units, external-CSV limits and ML examples.

With Windows MT5 open, export the exact broker symbol and use a **new output filename**:

```powershell
.\.venv\Scripts\python.exe scripts\export-history.py --symbol EURUSDm --count 50000 --output runtime\EURUSDm-M30.csv
```

Export also creates `runtime\EURUSDm-M30.meta.json`. Keep the pair together and do not edit/relabel synthetic data as broker history. Research requires at least 8,000 completed M30 bars and USD account/profit currency. Costs must be selected explicitly from the broker/account: spread and slippage in **price units**, commission in USD per lot round trip, and nonnegative conservative overnight swap cost in USD per lot/day. The [research guide](docs/RESEARCH.md) shows all required arguments. No inferred cost defaults or no-trade reports establish profitable performance.

For Android/iPhone home-screen installation and private HTTPS access, see [mobile/weekend onboarding](docs/MOBILE.md). The terminal includes home-screen metadata/icons and a private Tailscale Serve helper; actual phone routing/login must be configured on your devices. Saturday connection tests separate historical charts from fresh-quote trading readiness.

See [validation and remaining work](docs/VALIDATION.md), [acceptance gates](docs/ACCEPTANCE.md), [staged deployment](docs/DEPLOYMENT.md) and the separate [commercial control-plane guide](docs/COMMERCIAL.md). Live trading and a billing provider are unavailable. Real-history results, broker-specific demo execution, physical phone acceptance, extended observation, provider calendar refresh, customer deployment/security review and relevant broker/legal requirements remain outstanding. A working interface or test suite is not a release decision.
