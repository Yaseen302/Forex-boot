# Acceptance evidence and remaining gates

A feature being implemented, tested with a fake broker, and confirmed on the real Windows/Exness installation are three different states. Nothing in this checklist promises returns. Four days of demo observation is a technical check, not evidence that the strategy will be profitable or ready for customers.

| Evidence status | Meaning |
|---|---|
| Code implemented | The source and a repeatable command exist. |
| Mock checked | Automated checks use fixtures/fake clocks/fake broker responses. They do not place Exness orders. |
| Windows user confirmed | The user supplied evidence from their machine for the particular check. |
| Unverified | Required external execution or evidence is still missing. |

## Current evidence

| Area | Evidence and present limit |
|---|---|
| Dashboard and installation | **Windows user confirmed:** screenshots show a built dashboard, a running localhost backend and the initial test run. Later changes still require an update on that PC. |
| MT5 demo connection | **Windows user confirmed:** the October 17 screenshot shows MT5 demo, terminal 3/3 and history 7/7. This confirms that connection/history check, not order execution. |
| Account funding and permissions | **Unverified:** the supplied screenshot shows equity/free margin 0.00 and disabled MT5 Algo Trading. The user must verify virtual demo funds and permissions before any execution. |
| Phone connection | **Windows user confirmed:** Tailscale devices/Serve readiness were shown. **Unverified:** authenticated ForexLab access and use on a physical Android phone and iPhone. |
| Strategy, risk and execution guards | **Code implemented / mock checked.** Real broker specs, fills, SL/TP, deal reconciliation and loss-limit behavior must still be checked on the selected demo account. |
| Soak evidence collector | **Code implemented / mock checked:** `tests/test_observation.py` covers read-only transport, invalid readings, stale/future quotes, same-account recovery, account changes, persistence, clock rollback, duration and redaction. No real observation period has been completed by these tests. |
| Automatic startup | **Code implemented:** reviewed Task Scheduler instructions and an analysis-only launcher are supplied in `DEPLOYMENT.md`. **Unverified:** task registration, Windows reboot and broker reconnection. No task is installed by the cloud. |
| Market-performance evaluation | **Unverified:** real Exness history and held-out evaluation results are needed. Synthetic/fake data tests verify the engine only. |
| Live money and customers | **Unverified / unavailable for release:** the current application blocks live execution. Commercial deployment requires separate isolation, authorization and operational review. |

## Gate 1: Connection and mobile acceptance

1. Use the exact broker symbol (for example `EURUSDm`) and the intended terminal installation. Check the actual demo account in MT5. Never enter the broker password in ForexLab or chat.
2. Run `scripts/check-mt5.ps1 -Symbol EURUSDm`. Terminal and available history can pass during weekends; stale quotes must block new entries.
3. Verify the virtual demo balance in Exness and the account's trading permissions. Keep actual money out of this acceptance test.
4. Use the private HTTPS phone address created by `scripts/enable-mobile.ps1`. Verify Android Chrome and iPhone Safari login, chart touch/zoom, indicator settings, tabs and emergency-stop state. Lock/reload the page and verify that the token is requested again.
5. Save an allowlisted support report. Do not send an unredacted session token, broker login, terminal data directory or database.

Pass evidence: dated screenshots without credentials and the read-only connection report. A green connection is not a trading signal.

## Gate 2: Controlled demo execution

Perform only after the market supplies fresh quotes, account permissions and nonzero virtual equity pass, and the bot's strategy actually produces a valid signal. Keep risk limits; do not force a signal or increase risk to obtain a screenshot.

- Start one backend with the documented explicit demo opt-in. Confirm the broker still reports DEMO before enabling automation in the UI.
- Review the news/calendar gate. The manual clearance expires; this version must not be described as unrestricted unattended trading.
- Let a valid strategy decision pass through the risk engine. A WAIT/no-trade period is acceptable evidence of guards, not evidence of execution.
- In MT5, verify the resulting order/deal, exact symbol, volume, direction, fill, SL and TP against the application journal. Check that the risk allowance was respected. Save redacted evidence.
- Test emergency stop for new entries, duplicate prevention and restart behavior. Existing positions require separate broker inspection; entry stop does not close them.
- On ambiguity, stop automation and inspect broker history before reconciling. Do not clear a pending lock just to try again.

Pass evidence: actual demo broker ticket/deal and the matching local journal, with no unexplained duplicate, missing protection, or unresolved submission. Mock tests alone cannot pass this gate.

## Gate 3: Observation and recovery

A read-only collector can run alongside the single backend. It never enables automation or sends orders:

```powershell
powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\scripts\observe-demo.ps1 -Symbol EURUSDm -Sample
powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\scripts\observe-demo.ps1 -Symbol EURUSDm -Hours 96 -IntervalSeconds 60
```

The second command requests 96 hours; the report records **only actual collected readings and elapsed intervals**. It cannot complete a four-day test instantly. Keep the machine awake, MT5 open and the observer running. Stopping the observer, rebooting or sleeping creates gaps; restarting does not fill them.

```powershell
powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\scripts\observe-demo.ps1 -Symbol EURUSDm -ReportOnly
powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\scripts\collect-support.ps1 -Symbol EURUSDm
```

Review `runtime/observation-report.json` and `runtime/support-observation-<UTC timestamp>.json`. They contain account hashes, safe operational counters and summary evidence, not credentials or raw journal payloads. Observation identity hashes remain linkable inside this database; review the report before sharing.

During an operator-supervised demo-only test with no ambiguous submissions, interrupt the terminal connection and restore it. The next valid reading of the **same account** records a verified recovery. A different account creates a new equity comparison instead. A connection interruption between polls may be missed; sampled evidence is not continuous network monitoring. Restarting the app must leave automation off until explicitly enabled again.

After intentionally resetting/refilling a demo account, begin a new comparison baseline without deleting old evidence:

```powershell
powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\scripts\observe-demo.ps1 -Symbol EURUSDm -Sample -ResetComparison
```

The report preserves earlier segments. Balance changes can be deposits, withdrawals, resets or realized P/L; sampled drawdown is not cashflow-adjusted performance. A fresh-quote UTC date only means at least one observed fresh quote on that date. Weekend observations do not count as four full market sessions or coverage of different market regimes.

Pass evidence: actual elapsed observation, verified demo samples, recorded failures/recoveries, explained gaps, broker reconciliation and operator review. Longer testing across market conditions is still necessary. No report automatically enables live trading.

## Gate 4: Research and production decision

Use real broker history with realistic costs and chronological out-of-sample evaluation. Save the dataset provenance, broker timezone/session assumptions, costs, configuration, trade count and held-out results. No-trade or losing results must be reported as such. Do not tune on the test period and then describe it as held out.

An isolated offline ML experiment is available now and cannot affect orders; it does not satisfy any demo or release gate. See [RESEARCH.md](RESEARCH.md). Only after the earlier gates pass should there be a separate decision about model integration or a commercial product. Per-user authorization, account isolation, licensing/billing, backup/restore, incident response, capacity testing and relevant legal/broker requirements need their own evidence. A four-day demo result, passing unit tests or a polished mobile screen does not replace these gates.
