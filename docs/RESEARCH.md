# Broker history, reports and isolated ML research

Research reads completed M30 history and writes local reports. It never sends orders, enables automation, removes an uncertain-order lock or promotes a trained model into trading. A profitable historical window is not a profit guarantee. Zero/low trades, losses, missing history and failed runs must remain visible.

## Use the dashboard

1. Update the existing Windows installation, start `scripts/start-windows.ps1 -Source mt5`, sign in with the current session token and select the exact broker symbol in Charts.
2. In **Analysis → Research & reports**, choose **Export closed MT5 history**. MT5 must be running and have at least 8,000 completed M30 candles available. Increase the desktop terminal's history limit and load history if the export is short. Export is read only and can work while the market is closed; it does not require new-order permission.
3. Review dataset source, timestamp range, gaps, account/profit currency and broker contract specifications. USD account and USD profit currency with supported linear contracts are currently required. Cross-currency conversion is not simulated.
4. Enter each cost assumption from the selected broker/account, then confirm it. Spread/slippage are price differences, not pips/points. Commission is USD per lot round trip. Swap is a conservative **nonnegative debit** in USD per lot per UTC overnight. Enter zero only if you explicitly accept that assumption. For example, 20 points at point size 0.00001 equals a price spread of 0.00020; this is a unit conversion, not a quote for Exness.
5. Run fixed-rule chronological evaluation. Wait for the job to complete and review development/validation/out-of-sample trade counts, net results, drawdown, costs and full JSON. Download the report privately. Interrupted jobs are recorded as failed rather than fabricated as successful.
6. Optional **ML research comparison** forecasts a fixed-horizon long-only outcome after the entered costs. It is a separate forecasting experiment, not a replay of the strategy's SL/TP execution. Its metrics never enable trading.

CSV import accepts up to 10 MB in the dashboard, columns `time,open,high,low,close,volume`, UTC Unix M30 open timestamps, completed bid OHLC and declared instrument specifications. Imports remain `external_csv_unverified` even when you acknowledge them for research. Missing specifications, malformed bars and short history block a run. Synthetic fixtures cannot be evaluated as broker-performance evidence. A user-controlled file/sidecar cannot cryptographically prove its own origin.

## Export and run from Windows PowerShell

Use the existing project folder, virtual environment and logged-in MT5 terminal. Do not enter broker credentials in scripts, chat or the website. `MT5_TERMINAL_PATH`, if set, selects an intended installed terminal. Choose a new output filename; an existing dataset is preserved.

```powershell
Set-Location (Join-Path $env:USERPROFILE 'ForexLab')
.\.venv\Scripts\python.exe scripts\export-history.py --symbol EURUSDm --count 50000 --output runtime\EURUSDm-M30.csv
if ($LASTEXITCODE -ne 0) { throw 'History export failed; inspect the error before evaluating.' }
```

`EURUSDm` is an example; use Market Watch's exact symbol. Keep the exported CSV and matching `.meta.json` together. The sidecar records non-secret server provenance, instrument specs, row count, range and SHA-256 of the CSV. Edits to the data invalidate the hash. Review export issues; a successful export can still contain too few bars for research.

The next commands prompt for **your reviewed cost assumptions**; type decimals with a period. They do not guess costs or silently supply zero:

```powershell
$spread = Read-Host 'Reviewed spread: price difference'
$slippage = Read-Host 'Reviewed adverse slippage per fill: price difference'
$commission = Read-Host 'Reviewed commission: USD per lot round trip'
$swapDebit = Read-Host 'Reviewed nonnegative swap cost: USD per lot per UTC overnight'
.\.venv\Scripts\python.exe -m backend.backtest runtime\EURUSDm-M30.csv --spread $spread --slippage $slippage --commission $commission --swap $swapDebit --output runtime\backtest.json
if ($LASTEXITCODE -ne 0) { throw 'Backtest failed; no result should be claimed.' }
.\.venv\Scripts\python.exe -m backend.evaluate runtime\EURUSDm-M30.csv --spread $spread --slippage $slippage --commission $commission --swap $swapDebit --output runtime\evaluation.json
if ($LASTEXITCODE -ne 0) { throw 'Evaluation failed; no result should be claimed.' }
.\.venv\Scripts\python.exe -m backend.research runtime\EURUSDm-M30.csv --spread $spread --slippage $slippage --commission $commission --swap $swapDebit
if ($LASTEXITCODE -ne 0) { throw 'Research report generation failed.' }
```

The strategy backtest/evaluate/research CLI workflows validate the metadata pair and require at least 8,000 completed M30 candles. Backtest creates one simulator report; evaluate creates fixed-rule 60/20/20 and three rolling windows; research adds approved provenance/cost metadata and a uniquely named persisted report. Initial simulated equity defaults to USD 1,000; use `--initial` to change that assumption. It is not a deposit instruction or actual account balance. Other controls are shown by `--help`.

Reports mark floating equity at bar close and retain separate closed-equity drawdown. Intrabar drawdown, broker margin/stop-outs, varying spread, exact rollover/triple swap, tick paths, news-time liquidity and currency conversion are not reconstructed. UTC D1/H4 aggregation is not verified against Exness session boundaries or DST. Consequently `live_strategy_parity_validated` remains false. Rolling windows overlap chronological validation/OOS periods; do not combine them as independent evidence. Tuning after inspecting a test window requires fresh untouched data.

## ML command line

Development setup installs the optional pinned `requirements-ml.txt` stack and its tests. A lean runtime using only `requirements.txt` does not include it. To add just the research stack to an existing virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-ml.txt
if ($LASTEXITCODE -ne 0) { throw 'Optional research dependencies failed to install.' }
```

The ML CLI uses **points**, unlike the strategy CLI's price differences. It also uses **signed long swap**, where a debit is negative. The dashboard handles conversion from its shared nonnegative debit field. This CLI prompts for the actual reviewed inputs rather than assuming a contract/point size:

```powershell
$pointSize = Read-Host 'Broker point size: price units'
$spreadPoints = Read-Host 'Reviewed spread: broker points'
$slippagePoints = Read-Host 'Reviewed adverse slippage per fill: broker points'
$commission = Read-Host 'Reviewed round-trip commission per lot: USD'
$signedSwap = Read-Host 'Signed long swap per lot/day: negative for debit, USD'
$contractSize = Read-Host 'Broker contract size'
.\.venv\Scripts\python.exe -m backend.ml_research runtime\EURUSDm-M30.csv --symbol EURUSDm --horizon 3 --point-size $pointSize --spread-points $spreadPoints --slippage-points $slippagePoints --commission-round-trip-per-lot $commission --swap-per-lot-day $signedSwap --contract-size $contractSize --timeframe-minutes 30 --quote-currency USD --output runtime\ml-research.json
if ($LASTEXITCODE -ne 0) { throw 'ML research failed; no validation pass was produced.' }
```

Unlike the dashboard dataset workflow, the standalone ML CLI reads a CSV directly and records its local hash rather than verifying a broker-export sidecar. It cannot attest the data source or verify that the final bar is complete; inspect the input first.

Lagged closed-bar features feed logistic regression with training-only scaling, purged chronological splits and expanding walk-forward windows. Reports compare Brier/log loss and calibration with training-derived prevalence/majority baselines and retain sample counts. Single-class or undersized windows abstain. These scores describe a fixed-horizon long forecast, not trading P/L, risk approval, statistical independence or a guarantee. Core execution does not load the model. Optional `--model-output` writes a local research artifact only; never load untrusted joblib/pickle files.

## Evidence still needed

Cloud fixture tests validate software, not historical Exness performance. No actual broker-history report, new Windows research-command run, complete multi-day observation period, broker fill/SL/TP result or public release is claimed by this guide. Collect real reports on the Windows PC, then follow [acceptance gates](ACCEPTANCE.md) and [deployment/recovery](DEPLOYMENT.md). Keep private runtime data out of Git and shared screenshots.
