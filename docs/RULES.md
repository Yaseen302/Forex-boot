# Exact strategy, costs and risk rules

## Market data and timeframe policy

`MT5Bridge.candles` requests position 1 onward, excluding the forming candle. All OHLC, volume and timestamps must be finite, candle times strictly increase, prices stay positive and OHLC bounds must be consistent. All 21 MT5 standard timeframes are chartable, subject to broker history. Entries use only D1/H4/M30; M5/M15 are visual inspection timeframes and do not silently change the entry model.

## Deterministic ICT/SMC approximations

These are explicit research definitions, not assertions that discretionary ICT methods have been reproduced completely.

- A pivot high must strictly exceed the highs of the previous two and next two **closed** candles; a pivot low must be strictly lower. A pivot only becomes available after the two right candles close. Equal highs/lows are not pivots.
- Two latest confirmed higher pivot highs and higher pivot lows mean bullish; two lower highs/lower lows mean bearish; everything else is mixed. Returned swings explain HH/HL/LH/LL comparisons.
- A fresh upward break requires the previous close <= last confirmed pivot high and latest close > it. Downward break is symmetric. A break against the current pivot trend is labelled CHoCH; other breaks are BOS candidates. Neither is a trade by itself.
- A bullish FVG exists when candle i.low > candle (i-2).high; the gap is those two prices. Bearish is symmetric. A bullish gap is fully filled when a later candle low reaches its lower boundary; bearish fills when a later high reaches the upper boundary. Partial fills remain visible.
- On the current fresh break, the latest opposing candle among the preceding 11 candles is an order-block candidate using full low/high bounds. Historical order-block lifecycle, displacement validation and breaker blocks are not implemented.
- Liquidity sweeps: current low pierces confirmed support but closes above it, or high pierces confirmed resistance but closes below it. Equal-high/low liquidity pools are not separately modelled.
- Support/resistance are the latest confirmed pivot low/high. These and candidate zones are contextual evidence; the current entry rule does not require a zone touch or sweep.
- ATR is the arithmetic average of the last 14 true ranges, with previous closes included.

## Entry / exit model

All D1, H4 and M30 trends must agree and be non-mixed. M30 must have a fresh same-direction BOS. Stop is latest M30 confirmed support for buys, resistance for sells. Its distance from the signal close must be between 0.5 and 5 ATR. Indicative target is 2.5 times that distance from the signal close; the extra headroom permits actual spread/slippage while enforcing at least 2R at the entry quote. SL/TP are rounded to the broker tick grid, then reward/risk is rechecked. The broker's stop-distance rules must pass. No stop is silently widened to force a trade. Gaps, spreads or quote drift may invalidate a signal.

Orders are accepted only in the first five minutes after M30 closes; quote age must be 0–30 seconds. D1/H4 history must not be unclosed or stale beyond their frame lengths. No session/calendar provider is integrated; fresh-tick/history filters and manual news clearance gate entries. Broker `order_check` handles broker-side trading/margin restrictions, not every economic event.

## Risk sizing and account limits

Default risk = equity * 0.25%. The broker computes stop P/L for one lot in the account currency using `order_calc_profit`; estimated adverse slippage and round-trip commission are added. Volume is floored to `volume_step` with decimal arithmetic. It is capped at `volume_max`. If below `volume_min`, skip. Estimated loss including configured costs must fit the budget. Actual fills/gaps can exceed any estimate; a stop is not a guaranteed maximum loss.

Account-wide position **plus pending order** limit is 1, including trades from outside this app. Daily loss is equity decline from first observed equity that UTC day, maximum drawdown from observed high-water equity; anchors are persisted by server/account. Cross-day carryover, deposits/withdrawals and offline equity changes are not cash-flow adjusted. Limits block new entries rather than flatten existing trades. While the app is running, polling/execution update anchors; data while offline cannot be inferred.

Defaults: 2% daily loss cap, 5% observed drawdown cap, spread 25 broker points, free-margin buffer 120% of calculated margin, maximum quote age 30 seconds, minimum price reward/risk 2. Costs: 7 account-currency units per lot round trip and 10 broker points of adverse slippage. **Replace cost settings with the broker/account's actual conservative costs.** Net RR after costs can be lower than price RR.

Configuration uses exported variables `RISK_` + uppercase dataclass field name, for example `RISK_RISK_PERCENT=0.25`, `RISK_COMMISSION_PER_LOT=7`, `RISK_SLIPPAGE_POINTS=10`, `RISK_MAX_SPREAD_POINTS=25`, `RISK_MAX_TICK_AGE=30`, `RISK_MAX_DAILY_LOSS=2`, `RISK_MAX_DRAWDOWN=5`, `RISK_MIN_RR=2`. Risk cannot exceed 0.5%, account limits cannot expand past the evaluation defaults, position limit stays 1 and minimum RR cannot drop below 2. Invalid values fail closed. Changing settings requires process restart. Do not put tokens in settings committed to Git.

## Execution and recovery

The server must have `DATA_SOURCE=mt5`, `ENABLE_DEMO_EXECUTION=1`, a valid authenticated request/opt-in worker, broker-confirmed demo account, required terminal/account permissions, manual news clearance, no emergency and all risk gates. Real accounts are always rejected; no live endpoint exists. After broker `order_check`, account identity/demo mode, trading permissions, quote, equity/budget, positions/orders, spread, margin, news clearance and entry freshness are rechecked before submission. Quote movement outside the configured entry tolerance is rejected. This narrows the gap between evaluation and send but does not create an atomic transaction with external terminal activity. Only broker symbols supporting FOK are handled; other fill modes need a separately validated adapter.

`order_check` must return 0. A durable pending signal keyed by server/login/symbol/M30 candle/side is written **before** `order_send`. A DONE response plus matching broker deal history is required for local filled status. Timeouts, missing results, other retcodes and unconfirmed history remain pending and block later submissions, including after restart. Reconciliation is manual in this version; do not clear the ledger as a retry mechanism. Single Uvicorn worker is required; multiple backends/processes against the same account are unsupported.

Broker SL/TP remain when the process stops. The emergency switch and automation-off switch do not close positions. No guarantee is made that broker-side stops survive a rejected modification or external manual changes; inspect the actual MT5 position.

## Backtesting and OOS evaluation

Input CSV columns: `time,open,high,low,close,volume`, integer UTC epoch **M30 open** timestamps, ascending, bid OHLC. Minimum 1600 bars (roughly 30-day higher-timeframe warmup) for a run; 8000 for 60/20/20 chronological/rolling research. Dataset gaps and broker calendars must be reviewed; fixed UTC resampling may not match broker D1 session boundaries/DST.

Only fully closed higher-timeframe aggregates enter the signal at each M30 open. Signals use previous completed M30 candles; the earliest fill is the next candle's open. First partial H4/D1 buckets are excluded. No future data enters feature calculations. A carried position that exits during a candle cannot fund a replacement trade at that same candle's earlier open. Entry freshness is also checked after market/history gaps. One position at a time. Constant spread, adverse entry/stop/terminal slippage, per-lot round-trip commission and nonnegative per-lot/day swap estimates are included. Short exits use ask (bid OHLC + spread); long exits use bid. If both barriers hit, stop takes precedence. Stop gaps fill at the worse open. The last open position is closed at the end of available data.

Results include net, win rate, profit factor, expectancy, trade count and **closed-equity** maximum drawdown. No-trade runs report null rates. Floating intratrade drawdown, exact variable spreads, exact Wednesday triple-swap, historical broker margin, market impact, live economic-calendar/spread filters, currency conversion and realistic liquidity cannot be inferred from OHLC. Current contract simulation is for USD-quoted instruments in a USD account with a configured contract size, not general cross-currency trading. Use broker tick-level testing before live decisions.

`backend.evaluate` keeps the rules fixed across development/validation/OOS windows and rolling OOS windows. It does not perform ML training or data-driven parameter selection. Warmup is retained before evaluation boundaries but is not traded. No profitability, baseline superiority or statistical significance is asserted. If these rules/costs are tuned, reserve new untouched OOS data.


## Chart indicators and presentation

Each chart indicator has independent settings and requires a complete warmup. SMA is the arithmetic trailing mean; EMA starts with a complete-period SMA seed and alpha=2/(period+1). Bollinger bands use the population standard deviation of their own trailing window times the configured multiplier. RSI uses Wilder smoothing; all-flat prices produce50, rising with no losses produces100, falling with no gains produces0. MACD is independently seeded fast EMA minus slow EMA; its signal is an EMA of the MACD line and histogram is MACD minus signal. RSI/MACD panes share the main chart's visible time range. Chart periods/overlays are visual tools and never change the backend entry/risk rules. Broker-provided digits and tick size govern price display when using MT5. Refresh preserves the visible chart range; changing symbol/timeframe initially fits the new history.
