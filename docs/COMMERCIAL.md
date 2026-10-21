# Optional customer metadata service

`control_plane` is a separate, opt-in service for manual customer/license administration, device enrollment and self-reported demo summaries. The main ForexLab backend does not depend on it. It has its own SQLite database, process and administrator token. It has no MT5 import, broker password field or order execution endpoint. Revoking a license blocks metadata access; it does not stop a running Windows bot or close broker positions.

This is a tested foundation for a future customer product. Subscription payments, automatic activation, account recovery, verified performance, customer bridge packaging and public production deployment are not implemented. Customer reports are unverified inputs, not broker statements or proof of profitability. Multiple enrolled devices reporting the same broker account can double-count results; the service deliberately does not collect account login identifiers to deduplicate them.

## Private development launch

Use the project's existing virtual environment and core requirements. Run this independently of the MT5 backend. In PowerShell, from the project directory:

```powershell
$env:CONTROL_PLANE_ADMIN_TOKEN = & .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
$env:CONTROL_PLANE_DATABASE_PATH = Join-Path $PWD 'runtime\control-plane.sqlite'
$env:CONTROL_PLANE_HOSTS = 'localhost,127.0.0.1'
$env:CONTROL_PLANE_ALLOW_HTTP = '1'
& .\.venv\Scripts\python.exe -m uvicorn control_plane.app:create_app --factory --host 127.0.0.1 --port 8100 --workers 1
```

The loopback HTTP exception is for local development only. An administrator token must contain 32–256 printable ASCII characters without whitespace. Generate a random value; store it in a protected secret manager before using persistent service data. The generated example above changes the token on each new shell run. Restarting with a different token changes administrator access, while existing hashed license/device credentials remain stored in the database. Do not print the administrator token to a support transcript or pass it as a command argument.

`GET /health` reports service health without customer data. The customer portal is `/portal`; it accepts a customer license key, never the administrator token or an MT5 password. The key stays in page memory; sign-out, page navigation and page close clear it. No browser storage or third-party scripts are used. A new device credential appears once after enrollment and must be saved securely before hiding it. The local trading backend currently does not upload summaries automatically.

## Manual operator workflow

The CLI prompts for the administrator token with hidden input and refuses redirects. Supply the local URL for development; use a private HTTPS URL for remote access. For example:

```powershell
& .\.venv\Scripts\python.exe -m control_plane.admin --url http://127.0.0.1:8100 create-customer --name 'Demo customer'
& .\.venv\Scripts\python.exe -m control_plane.admin --url http://127.0.0.1:8100 list-customers
& .\.venv\Scripts\python.exe -m control_plane.admin --url http://127.0.0.1:8100 issue-license --customer-id CUSTOMER_ID_FROM_RESPONSE --days 30 --seats 1
& .\.venv\Scripts\python.exe -m control_plane.admin --url http://127.0.0.1:8100 list-licenses --customer-id CUSTOMER_ID_FROM_RESPONSE
& .\.venv\Scripts\python.exe -m control_plane.admin --url http://127.0.0.1:8100 revoke-license --license-id LICENSE_ID_FROM_RESPONSE
& .\.venv\Scripts\python.exe -m control_plane.admin --url http://127.0.0.1:8100 revoke-device --device-id DEVICE_ID_FROM_RESPONSE
```

Replace the uppercase placeholders with exact response IDs. Issuance displays the new opaque license key once; store and deliver it privately. The database stores SHA-256 hashes of high-entropy keys, not their recoverable values. The key is a bearer credential: anyone holding it can access that customer's metadata and enroll devices up to the seat limit. Use a distinct customer for each tenant. Multiple licenses of one customer share that customer's device and performance views.

Device enrollment is atomic, so concurrent requests cannot overfill seats. Expired or revoked licenses invalidate customer access and all related device credentials. Revoking a device frees its seat and invalidates its credential. There is no credential recovery endpoint; replace credentials by revoking and issuing/enrolling again. Keep an audit of these manual operator actions outside the service until an immutable administration audit feature is implemented.

## API boundaries

| Credential | Routes | Capability |
| --- | --- | --- |
| None | `GET /health`, `/portal`, `/portal.js`, `/portal.css` | Health and static portal assets |
| Administrator | `POST/GET /v1/admin/customers`, `POST/GET /v1/admin/licenses`, `POST /v1/admin/licenses/{id}/revoke`, `POST /v1/admin/devices/{id}/revoke` | Manage customer metadata and revoke access |
| Customer license | `GET /v1/customer/me`, `/devices`, `/performance`; `POST /v1/customer/devices/{id}/revoke`; `POST /v1/enroll` | Own customer's metadata and device seats |
| Device credential | `POST /v1/device/heartbeat`, `PUT /v1/device/reports` | Own heartbeat and dated summary |

Authenticated calls use `Authorization: Bearer ...`; secrets do not belong in URLs. A heartbeat accepts only `app_version`. Reports accept `report_date` (UTC date), `currency` (three uppercase letters), `closed_trades`, `wins`, `losses`, decimal `realized_pnl` and finite `max_drawdown_pct`. Counts are 0–10,000; wins plus losses cannot exceed closed trades. A zero-trade report requires zero realized PnL. Reports replace the same device/date/currency row, making repeated daily submissions idempotent. Different currencies are never converted or added together. Aggregated daily maximum drawdown is not an account-level drawdown calculation.

Unknown payload fields are rejected without echoing their contents. Every request body is limited to 16 KiB. The service enforces explicit allowed hosts, HTTPS by default, no-store responses, content security policy, request limits and authentication-attempt limits. Default limits are per IP and per process: 180 requests/minute and 12 failed authentications/minute. Use one worker. Reverse-proxy deployments need correctly scoped proxy-header trust; otherwise addresses and HTTPS detection can be wrong. Shared rate limiting is needed before scaling to multiple workers.

## Remote and production prerequisites

For a private HTTPS deployment, set `CONTROL_PLANE_ALLOW_HTTP=0` and `CONTROL_PLANE_HOSTS` to the exact private hostname, without scheme, port, path or wildcard. Keep Uvicorn bound to loopback behind the reviewed HTTPS proxy. If using Tailscale Serve, create a separate route deliberately: the current mobile helper serves the trading dashboard on port 8000 and must not be overwritten by metadata-service setup. Verify the real remote request scheme, allowed host and client address before enabling customer access. Do not expose the administrator API publicly as a shortcut.

Restrict database and secret files to the service account. Back up SQLite using its backup API or a consistent stopped-process copy, including WAL state; test restoration with matching code privately. Protect customer names, device labels and report data in backups. The service currently has no automated data deletion/retention workflow, billing, email, PostgreSQL migration, tamper-evident administration audit or security certification.

Before any public launch, complete tenant and load/security review, operator MFA through an identity gateway, secret rotation/recovery, backup/restore and retention/deletion procedures, incident monitoring, signed bridge distribution/updates, customer consent and the applicable broker/regulatory/legal review. The existing private MT5 account backend must remain isolated per customer. This session has not deployed this service or connected real customer data.
