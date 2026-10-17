# ForexLab

A local Forex research terminal: Python/FastAPI, React/TypeScript/Tailwind, TradingView Lightweight Charts, SQLite and an official Windows MT5 adapter. The uploaded prototype is preserved unchanged in `reference/` and is not the new application entry point.

**Status: research/demo implementation, not a validated profitable or commercial product. Live execution is unavailable.** No software can promise zero losses or turn $10 into $1,000 safely. Four demo days test connectivity and operations, not profitability.

## Start on Windows

Follow [the Windows guide](docs/WINDOWS.md) to install Python 3.11 x64, Node.js LTS and broker MT5 on a PC that currently has no tools. Extract this project into a folder such as `C:\ForexLab`.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup-windows.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\start-windows.ps1
```

The default uses visibly labelled synthetic development prices. The start script generates a session API token; paste it into the dashboard. The browser communicates with FastAPI, never directly with MT5.

With the MT5 terminal running and logged in, use `start-windows.ps1 -Source mt5` for read-only broker analysis. **Orders require a separate opt-in:** `start-windows.ps1 -Source mt5 -EnableDemo`, a broker-confirmed demo account, manual calendar clearance and all risk conditions. Automation is optional in the dashboard and resets to off after server restart.

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
- Explicit demo-only execution through broker `order_check`, FOK `order_send` and deal-history verification. Persistent duplicate and uncertain-submission protection.
- SQLite controls, orders and event journal; session API authentication for all data and control endpoints. Read-only MT5 connection preflight checks exact symbols, contract specifications, terminal/account permissions, quote/history freshness and adapter support.
- M30 OHLC cost-aware backtester and fixed-rule chronological/rolling evaluation tools. No real-price profitability report is supplied because broker history has not been provided.

## Test and research

```bash
.venv/bin/python -m pytest -q
cd frontend
npm test
npm run build
```

On Windows use `.venv\Scripts\python.exe` instead. Export broker history using `scripts/export-history.py`, then run:

```powershell
.\.venv\Scripts\python.exe scripts\export-history.py --symbol EURUSD --count 50000
.\.venv\Scripts\python.exe -m backend.backtest runtime\EURUSD-M30.csv --swap 0
.\.venv\Scripts\python.exe -m backend.evaluate runtime\EURUSD-M30.csv --swap 0
```

`--swap 0` is appropriate only if the broker/account actually has zero overnight charges; otherwise use a conservative positive cost per lot/day. Other costs and limitations are described in [strategy and risk rules](docs/RULES.md).

For Android/iPhone home-screen installation and private HTTPS access, see [mobile/weekend onboarding](docs/MOBILE.md). The terminal includes home-screen metadata/icons and a private Tailscale Serve helper; actual phone routing/login must be configured on your devices. Saturday connection tests separate historical charts from fresh-quote trading readiness.

See [validation and remaining work](docs/VALIDATION.md). ML, commercial licensing, multi-user isolation, automatic economic-calendar ingestion and live trading are not implemented. A real broker connection, broker-specific execution, several market regimes and extended demo observation remain necessary before considering any live implementation.
