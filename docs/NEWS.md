# Economic-calendar entry gate

The default `NEWS_MODE=manual` requires the operator to review a real economic calendar and explicitly grant at most 15 minutes of clearance in Trade. Missing/expired clearance blocks new entries. Server restart is not permission to trade, and a stale/future quote remains blocked even when news clearance is active.

Optional `NEWS_MODE=calendar` reads a local provider-produced JSON file through `NEWS_CALENDAR_PATH`. It does **not** download economic events, sign up for a provider, invent empty calendars or obtain credentials. A provider with suitable coverage, update reliability and redistribution terms still needs to be selected and integrated. Do not describe this as an operational automatic news feed until that has been verified on the actual installation.

## Feed contract

| Field | Required value |
|---|---|
| `schema_version` | Integer `1`. |
| `provider` | Nonempty real provider identifier. |
| `fetched_at` | Numeric UTC Unix timestamp of the actual retrieval; must be no more than 900 seconds old and cannot be in the future. |
| `coverage_from`, `coverage_until` | Numeric UTC Unix boundaries for the feed's verified coverage. They must cover the complete current blackout window. |
| `events` | Array of at most 10,000 objects. Each has numeric UTC Unix `time`, uppercase `currency` and `impact` equal to `low`, `medium` or `high`. |

Supported currency identifiers are EUR, USD, GBP, JPY, AUD, NZD, CAD, CHF, XAU, XAG, BTC and ETH. Exact broker symbols such as `EURUSDm` map to the first currency pair; an unmappable symbol fails closed. Malformed events, unsupported impact/currency fields, missing files, stale/future timestamps and insufficient coverage block entries. A relevant high-impact event at or inside the configured buffer before/after now blocks entries. Low/medium events are not blocked by this rule; that is a defined limitation, not a claim that trading through them is safe.

`NEWS_BUFFER_MINUTES` defaults to 30 and accepts integer values from 15 to 120. The calendar gate replaces manual review for execution in this mode; granting manual clearance cannot override a blocked/missing calendar. It never overrides quote freshness, risk limits, account permissions or the demo-only requirement.

## Configure a verified local provider feed

Only after an external adapter is writing complete, fresh provider data to a private local file, set these variables in the **same PowerShell window** before starting ForexLab:

```powershell
$env:NEWS_MODE = 'calendar'
$env:NEWS_CALENDAR_PATH = Join-Path $env:USERPROFILE 'ForexLab\runtime\economic-calendar.json'
$env:NEWS_BUFFER_MINUTES = '30'
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-windows.ps1 -Source mt5
```

This starts analysis only. Use your actual project/feed path if different. The provider adapter should replace a fully written file atomically, preserve real UTC event times and state coverage accurately. Keep provider credentials outside the feed and repository; only the adapter needs them. Do not update `fetched_at` without a successful real retrieval or generate an empty list to unblock trading. A provider outage must leave entries blocked. Test stale feed, relevant events, malformed events and missing coverage while still in analysis/demo acceptance.

To return deliberately to operator-reviewed mode, stop the backend, set `$env:NEWS_MODE = 'manual'`, then restart analysis. Review the calendar before any later demo clearance. This does not resolve broker orders or change account/Algo Trading permissions.

## Scope of evidence

Fixture tests validate parsing, currency relevance, staleness and blackout decisions. They do not validate a provider's completeness, event revisions, licensing, live ingestion or latency. No actual provider is configured by these instructions, and no economic-calendar filter guarantees against loss.
