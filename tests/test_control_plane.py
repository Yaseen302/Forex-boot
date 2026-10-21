"""The optional license service cannot reach broker execution or another tenant."""
import concurrent.futures
import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from control_plane.app import Settings, create_app


ADMIN = "test-only-admin-token-" + "a" * 32


@pytest.fixture
def service(tmp_path):
    path = tmp_path / "metadata.sqlite"
    app = create_app(Settings(str(path), ADMIN, ("testserver",)))
    with TestClient(app, base_url="https://testserver") as client:
        yield client, path


def auth(token):
    return {"Authorization": "Bearer " + token}


def tenant(client, name="Customer A", seats=1):
    response = client.post("/v1/admin/customers", headers=auth(ADMIN), json={"name": name})
    assert response.status_code == 201
    customer_id = response.json()["id"]
    response = client.post("/v1/admin/licenses", headers=auth(ADMIN), json={"customer_id": customer_id, "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(), "seat_limit": seats})
    assert response.status_code == 201
    return customer_id, response.json()


def enroll(client, license_key):
    return client.post("/v1/enroll", headers=auth(license_key), json={"label": "Windows demo bridge"})


def daily(**overrides):
    return {"report_date": datetime.now(timezone.utc).date().isoformat(), "currency": "USD", "closed_trades": 4, "wins": 2, "losses": 1, "realized_pnl": "12.3400", "max_drawdown_pct": 1.5, **overrides}


def test_configuration_fails_closed(tmp_path, monkeypatch):
    monkeypatch.delenv("CONTROL_PLANE_ADMIN_TOKEN", raising=False)
    with pytest.raises(ValueError, match="ADMIN_TOKEN"):
        create_app()
    for token in ("short", " " * 40, "ü" * 40, "a" * 32 + "\n", "a" * 32 + " secret", "a" * 32 + "\x7f"):
        with pytest.raises(ValueError):
            Settings(str(tmp_path / "db"), token)
    for hosts in (("*",), ("*.example.com",), ("https://example.com",), ("example.com:8000",)):
        with pytest.raises(ValueError):
            Settings(str(tmp_path / "db"), ADMIN, hosts)
    with pytest.raises(ValueError, match="loopback"):
        Settings(str(tmp_path / "db"), ADMIN, ("example.com",), allow_http=True)


def test_https_host_auth_and_health_have_no_private_metadata(service):
    client, _ = service
    assert client.get("/health").json() == {"status": "ok", "service": "license-metadata", "broker_execution": False}
    assert client.get("/health").headers["cache-control"] == "no-store"
    assert client.get("/health").headers["strict-transport-security"].startswith("max-age=")
    assert client.get("http://testserver/health").status_code == 400
    assert client.get("https://attacker.example/health").status_code == 400
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/v1/admin/customers").status_code == 401
    assert client.get("/v1/admin/customers", headers=auth("wrong" * 10)).status_code == 401


def test_keys_shown_once_and_only_hashes_stored(service):
    client, path = service
    customer_id, license_data = tenant(client)
    license_key = license_data["license_key"]
    response = enroll(client, license_key)
    assert response.status_code == 201
    device_data = response.json()
    listing = client.get("/v1/admin/licenses", headers=auth(ADMIN), params={"customer_id": customer_id})
    assert listing.status_code == 200
    assert license_key not in listing.text
    listing = client.get("/v1/customer/devices", headers=auth(license_key))
    assert listing.json()[0]["id"] == device_data["device_id"]
    assert device_data["device_credential"] not in listing.text
    with sqlite3.connect(path) as db:
        stored = json.dumps({"licenses": db.execute("SELECT * FROM licenses").fetchall(), "devices": db.execute("SELECT * FROM devices").fetchall()})
    assert license_key not in stored
    assert device_data["device_credential"] not in stored
    assert ADMIN not in stored
    assert license_key not in client.get("/v1/customer/me", headers=auth(license_key)).text


def test_device_heartbeat_reports_and_idempotent_decimal_summary(service):
    client, _ = service
    _, license_data = tenant(client, seats=2)
    device_data = enroll(client, license_data["license_key"]).json()
    headers = auth(device_data["device_credential"])
    response = client.post("/v1/device/heartbeat", headers=headers, json={"app_version": "0.1.0"})
    assert response.status_code == 200
    assert response.json()["broker_execution"] is False
    assert client.put("/v1/device/reports", headers=headers, json=daily()).status_code == 200
    assert client.put("/v1/device/reports", headers=headers, json=daily(realized_pnl="10.1000")).status_code == 200
    second = enroll(client, license_data["license_key"]).json()
    assert client.put("/v1/device/reports", headers=auth(second["device_credential"]), json=daily(realized_pnl="0.2000")).status_code == 200
    summary = client.get("/v1/customer/performance", headers=auth(license_data["license_key"])).json()
    assert summary["totals"][0]["realized_pnl"] == "10.3000"
    assert summary["totals"][0]["closed_trades"] == 8
    assert summary["totals"][0]["device_days"] == 2
    assert "self-reported" in summary["verification"]
    listing = client.get("/v1/customer/devices", headers=auth(license_data["license_key"])).json()
    assert listing[0]["last_seen"] is not None


def test_customer_and_device_credentials_cannot_cross_boundaries(service):
    client, _ = service
    a_id, a = tenant(client, "A")
    b_id, b = tenant(client, "B")
    a_device = enroll(client, a["license_key"]).json()
    b_device = enroll(client, b["license_key"]).json()
    assert client.put("/v1/device/reports", headers=auth(b_device["device_credential"]), json=daily()).status_code == 200
    me = client.get("/v1/customer/me", headers=auth(a["license_key"])).json()
    assert me["customer"]["id"] == a_id and b_id not in json.dumps(me)
    assert len(client.get("/v1/customer/devices", headers=auth(a["license_key"])).json()) == 1
    assert client.get("/v1/customer/performance", headers=auth(a["license_key"])).json()["totals"] == []
    assert client.get("/v1/customer/performance", headers=auth(a["license_key"]), params={"device_id": b_device["device_id"]}).status_code == 404
    assert client.post("/v1/customer/devices/" + b_device["device_id"] + "/revoke", headers=auth(a["license_key"])).status_code == 404
    assert client.get("/v1/admin/customers", headers=auth(a["license_key"])).status_code == 401
    assert client.get("/v1/customer/me", headers=auth(a_device["device_credential"])).status_code == 401
    assert client.post("/v1/device/heartbeat", headers=auth(a["license_key"]), json={"app_version": "0.1"}).status_code == 401
    assert client.put("/v1/device/reports", headers=auth(a_device["device_credential"]), json=daily(device_id=b_device["device_id"])).status_code == 422


def test_seat_cap_revoke_frees_seat_and_invalidates_device(service):
    client, _ = service
    _, license_data = tenant(client)
    device_data = enroll(client, license_data["license_key"]).json()
    assert enroll(client, license_data["license_key"]).status_code == 409
    response = client.post("/v1/customer/devices/" + device_data["device_id"] + "/revoke", headers=auth(license_data["license_key"]))
    assert response.status_code == 200
    assert client.post("/v1/device/heartbeat", headers=auth(device_data["device_credential"]), json={"app_version": "0.1"}).status_code == 401
    assert enroll(client, license_data["license_key"]).status_code == 201


def test_parallel_enrollment_cannot_exceed_seat_cap(service):
    client, path = service
    _, license_data = tenant(client)
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        statuses = list(executor.map(lambda _: enroll(client, license_data["license_key"]).status_code, range(5)))
    assert statuses.count(201) == 1
    assert statuses.count(409) == 4
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM devices WHERE revoked=0").fetchone()[0] == 1


@pytest.mark.parametrize("state", ["revoked", "expired"])
def test_revoked_and_expired_license_invalidate_customer_and_device(service, state):
    client, path = service
    _, license_data = tenant(client)
    device_data = enroll(client, license_data["license_key"]).json()
    if state == "revoked":
        assert client.post("/v1/admin/licenses/" + license_data["id"] + "/revoke", headers=auth(ADMIN)).status_code == 200
    else:
        with sqlite3.connect(path) as db:
            db.execute("UPDATE licenses SET expires_at=? WHERE id=?", (time.time() - 1, license_data["id"]))
    assert client.get("/v1/customer/me", headers=auth(license_data["license_key"])).status_code == 401
    assert enroll(client, license_data["license_key"]).status_code == 401
    assert client.post("/v1/device/heartbeat", headers=auth(device_data["device_credential"]), json={"app_version": "0.1"}).status_code == 401
    assert client.put("/v1/device/reports", headers=auth(device_data["device_credential"]), json=daily()).status_code == 401


@pytest.mark.parametrize("expiry", ["2020-01-01T00:00:00Z", "2040-01-01T00:00:00Z", "2030-01-01T00:00:00", "NaN", "Infinity", 1e300, None])
def test_invalid_expiration_rejected(service, expiry):
    client, _ = service
    customer_id = client.post("/v1/admin/customers", headers=auth(ADMIN), json={"name": "A"}).json()["id"]
    response = client.post("/v1/admin/licenses", headers=auth(ADMIN), json={"customer_id": customer_id, "expires_at": expiry})
    assert response.status_code == 422


@pytest.mark.parametrize("changes", [{"realized_pnl": "NaN"}, {"realized_pnl": "Infinity"}, {"realized_pnl": "1e100"}, {"max_drawdown_pct": "NaN"}, {"max_drawdown_pct": "Infinity"}, {"wins": 5}, {"losses": -1}, {"closed_trades": True}, {"closed_trades": 10001}, {"closed_trades": 0, "wins": 0, "losses": 0}, {"currency": "usd"}, {"report_date": "2090-01-01"}, {"broker_password": "must-not-be-accepted"}])
def test_report_payload_bounds_and_nonfinite_values(service, changes):
    client, _ = service
    _, license_data = tenant(client)
    device_data = enroll(client, license_data["license_key"]).json()
    assert client.put("/v1/device/reports", headers=auth(device_data["device_credential"]), json=daily(**changes)).status_code == 422


def test_authentication_attempts_and_request_bytes_bounded(tmp_path):
    settings = Settings(str(tmp_path / "db.sqlite"), ADMIN, ("testserver",), authentication_failures_per_minute=3)
    with TestClient(create_app(settings), base_url="https://testserver") as client:
        for _ in range(3):
            assert client.get("/v1/admin/customers", headers=auth("wrong" * 10)).status_code == 401
        assert client.get("/v1/admin/customers", headers=auth(ADMIN)).status_code == 429
        response = client.post("/v1/admin/customers", headers=auth(ADMIN), content="x" * 16385)
        assert response.status_code == 413


def test_global_request_limit_and_http_dev_mode(tmp_path):
    settings = Settings(str(tmp_path / "db.sqlite"), ADMIN, ("testserver",), allow_http=True, requests_per_minute=2)
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/health").status_code == 200
        assert client.get("/health").status_code == 429


def test_no_currency_conversion_and_date_filter(service):
    client, _ = service
    _, license_data = tenant(client)
    device_data = enroll(client, license_data["license_key"]).json()
    for currency in ("USD", "EUR"):
        assert client.put("/v1/device/reports", headers=auth(device_data["device_credential"]), json=daily(currency=currency)).status_code == 200
    response = client.get("/v1/customer/performance", headers=auth(license_data["license_key"]))
    assert [item["currency"] for item in response.json()["totals"]] == ["EUR", "USD"]
    future = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
    assert client.get("/v1/customer/performance", headers=auth(license_data["license_key"]), params={"since": future}).json()["totals"] == []
    assert client.get("/v1/customer/performance", headers=auth(license_data["license_key"]), params={"since": future, "until": "2000-01-01"}).status_code == 422


def test_portal_assets_are_fixed_allowlisted_and_no_store(service):
    client, _ = service
    portal = client.get("/portal")
    assert portal.status_code == 200
    assert "Never enter an MT5 password here" in portal.text
    assert '<script src="/portal.js" defer></script>' in portal.text
    for path, media in (("/portal", "text/html"), ("/portal.js", "text/javascript"), ("/portal.css", "text/css")):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith(media)
        assert response.headers["cache-control"] == "no-store"
        assert "script-src 'self'" in response.headers["content-security-policy"]
        assert response.headers["x-frame-options"] == "DENY"
    assert client.get("/portal/app.py").status_code == 404
    assert client.get("/portal/../app.py").status_code == 404
    assert client.get("/v1/customer/me").status_code == 401


def test_validation_does_not_echo_accidental_secrets(service):
    client, _ = service
    secret = "accidental-secret-never-echo-this"
    response = client.post("/v1/admin/customers", headers=auth(ADMIN), json={"name": "A", "password": secret})
    assert response.status_code == 422
    assert secret not in response.text
    assert all("input" not in error for error in response.json()["detail"])


@pytest.mark.parametrize("command, arguments, method, path", [
    ("create-customer", ["--name", "Alice"], "POST", "/v1/admin/customers"),
    ("issue-license", ["--customer-id", "cus_" + "a" * 32], "POST", "/v1/admin/licenses"),
    ("revoke-license", ["--license-id", "lic_" + "a" * 32], "POST", "/v1/admin/licenses/lic_" + "a" * 32 + "/revoke"),
    ("revoke-device", ["--device-id", "dev_" + "a" * 32], "POST", "/v1/admin/devices/dev_" + "a" * 32 + "/revoke"),
    ("list-customers", [], "GET", "/v1/admin/customers"),
    ("list-licenses", ["--customer-id", "cus_" + "a" * 32], "GET", "/v1/admin/licenses?customer_id=cus_" + "a" * 32),
])
def test_operator_cli_prompts_hidden_and_disables_redirects(monkeypatch, capsys, command, arguments, method, path):
    from control_plane import admin
    import urllib.request

    seen = []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size): return b'{"ok":true}'

    class Opener:
        def open(self, request, timeout):
            assert request.full_url == "https://license.example" + path
            assert request.get_method() == method
            assert request.get_header("Authorization") == "Bearer " + ADMIN
            assert timeout == 20
            seen.append(request)
            return Response()

    def build(handler):
        if isinstance(handler, type):
            handler = handler()
        assert isinstance(handler, urllib.request.HTTPRedirectHandler)
        assert handler.redirect_request(None, None, None, None, None, None) is None
        return Opener()

    monkeypatch.setattr(admin.sys, "argv", ["admin", "--url", "https://license.example", command, *arguments])
    monkeypatch.setattr(admin.getpass, "getpass", lambda _: ADMIN)
    monkeypatch.setattr(admin.urllib.request, "build_opener", build)
    assert admin.main() == 0
    captured = capsys.readouterr()
    assert ADMIN not in captured.out + captured.err
    assert len(seen) == 1
