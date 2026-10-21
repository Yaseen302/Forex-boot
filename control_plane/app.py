"""Isolated, opt-in customer licensing and self-reported demo performance API.

Run with ``uvicorn control_plane.app:create_app --factory``. No module-level app
is instantiated: missing deployment secrets must fail before serving requests.
"""
from __future__ import annotations

import hashlib
import hmac
import math
import os
import re
import secrets
import sqlite3
import threading
import time
from collections import OrderedDict, deque
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware


def digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def identifier(prefix: str) -> str:
    return prefix + secrets.token_hex(16)


def utc_iso(value: float | None) -> str | None:
    return None if value is None else datetime.fromtimestamp(value, timezone.utc).isoformat()


@dataclass(frozen=True)
class Settings:
    database_path: str
    admin_token: str
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1")
    allow_http: bool = False
    requests_per_minute: int = 180
    authentication_failures_per_minute: int = 12

    def __post_init__(self):
        if not 32 <= len(self.admin_token) <= 256 or not self.admin_token.isascii() or any(ord(char) <= 32 or ord(char) == 127 for char in self.admin_token):
            raise ValueError("CONTROL_PLANE_ADMIN_TOKEN must contain 32–256 ASCII characters; generate a random secret")
        if not self.database_path or self.database_path == ":memory:":
            raise ValueError("Use a persistent SQLite database path")
        if not self.allowed_hosts or any(not re.fullmatch(r"[A-Za-z0-9.-]+", host) for host in self.allowed_hosts):
            raise ValueError("Configure explicit allowed host names; wildcards and URLs are not accepted")
        if self.allow_http and set(self.allowed_hosts) - {"localhost", "127.0.0.1", "testserver"}:
            raise ValueError("Plain HTTP is allowed only for loopback development hosts")
        if not 1 <= self.requests_per_minute <= 10000 or not 1 <= self.authentication_failures_per_minute <= 100:
            raise ValueError("Invalid rate limits")

    @classmethod
    def from_env(cls):
        return cls(
            database_path=os.environ.get("CONTROL_PLANE_DATABASE_PATH", "runtime/control-plane.sqlite"),
            admin_token=os.environ.get("CONTROL_PLANE_ADMIN_TOKEN", ""),
            allowed_hosts=tuple(host.strip() for host in os.environ.get("CONTROL_PLANE_HOSTS", "localhost,127.0.0.1").split(",")),
            allow_http=os.environ.get("CONTROL_PLANE_ALLOW_HTTP") == "1",
        )


class WindowLimiter:
    """Bounded in-process limiter. Deploy one worker or replace with shared limits."""

    def __init__(self, maximum: int):
        self.maximum = maximum
        self.entries: OrderedDict[str, deque] = OrderedDict()
        self.lock = threading.Lock()

    def allow(self, key: str, *, record: bool = True) -> bool:
        now = time.monotonic()
        with self.lock:
            bucket = self.entries.setdefault(key, deque())
            self.entries.move_to_end(key)
            while bucket and bucket[0] <= now - 60:
                bucket.popleft()
            if len(bucket) >= self.maximum:
                return False
            if record:
                bucket.append(now)
            while len(self.entries) > 10000:
                self.entries.popitem(last=False)
            return True


class RequestBoundary:
    """Require HTTPS, bound actual request bytes, and prevent secret-response caching."""

    def __init__(self, app, settings: Settings):
        self.app, self.settings = app, settings
        self.limiter = WindowLimiter(settings.requests_per_minute)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def secure_send(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend([(b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff"), (b"x-frame-options", b"DENY"), (b"referrer-policy", b"no-referrer"), (b"content-security-policy", b"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")])
                if scope.get("scheme") == "https":
                    headers.append((b"strict-transport-security", b"max-age=31536000"))
                message = {**message, "headers": headers}
            await send(message)

        async def reject(code, detail, headers=None):
            await JSONResponse({"detail": detail}, status_code=code, headers=headers)(scope, receive, secure_send)

        if not self.settings.allow_http and scope.get("scheme") != "https":
            return await reject(400, "HTTPS is required")
        client = (scope.get("client") or ("unknown", 0))[0]
        if not self.limiter.allow(client):
            return await reject(429, "Request rate exceeded", {"Retry-After": "60"})
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > 16384:
                return await reject(413, "Request body exceeds 16 KiB")
            if not message.get("more_body", False):
                break
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        return await self.app(scope, bounded_receive, secure_send)


class Store:
    def __init__(self, path: str):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Refuse symlinks: configuration must identify this service's own database.
        if Path(path).is_symlink():
            raise ValueError("Control-plane database cannot be a symlink")
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS customers (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS licenses (
                    id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(id),
                    key_hash TEXT UNIQUE NOT NULL, expires_at REAL NOT NULL,
                    seat_limit INTEGER NOT NULL CHECK(seat_limit BETWEEN 1 AND 50),
                    revoked INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS devices (
                    id TEXT PRIMARY KEY, license_id TEXT NOT NULL REFERENCES licenses(id),
                    credential_hash TEXT UNIQUE NOT NULL, label TEXT NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL,
                    last_seen REAL, app_version TEXT
                );
                CREATE TABLE IF NOT EXISTS reports (
                    device_id TEXT NOT NULL REFERENCES devices(id), report_date TEXT NOT NULL,
                    currency TEXT NOT NULL, closed_trades INTEGER NOT NULL,
                    wins INTEGER NOT NULL, losses INTEGER NOT NULL,
                    realized_pnl TEXT NOT NULL, max_drawdown_pct REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(device_id, report_date, currency)
                );
                CREATE INDEX IF NOT EXISTS licenses_customer ON licenses(customer_id);
                CREATE INDEX IF NOT EXISTS devices_license ON devices(license_id);
            """)
        if os.name != "nt":
            os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self, *, write=False):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.commit()
        except BaseException:
            if write:
                db.rollback()
            raise
        finally:
            db.close()


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("*", mode="after")
    @classmethod
    def no_control_characters(cls, value):
        if isinstance(value, str) and any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Control characters are not accepted")
        return value


class CustomerCreate(Payload):
    name: str = Field(min_length=1, max_length=100)


class LicenseCreate(Payload):
    customer_id: str = Field(pattern=r"^cus_[a-f0-9]{32}$")
    expires_at: AwareDatetime
    seat_limit: int = Field(default=1, ge=1, le=50, strict=True)

    @field_validator("expires_at")
    @classmethod
    def reasonable_expiration(cls, value):
        epoch = value.timestamp()
        if not math.isfinite(epoch) or not time.time() < epoch <= time.time() + 3660 * 86400:
            raise ValueError("Expiration must be in the next ten years and include a timezone")
        return value


class Enrollment(Payload):
    label: str = Field(min_length=1, max_length=80)


class Heartbeat(Payload):
    app_version: str = Field(min_length=1, max_length=40, pattern=r"^[a-zA-Z0-9.+_-]+$")


class DailyReport(Payload):
    report_date: date
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    closed_trades: int = Field(ge=0, le=10000, strict=True)
    wins: int = Field(ge=0, le=10000, strict=True)
    losses: int = Field(ge=0, le=10000, strict=True)
    realized_pnl: Annotated[Decimal, Field(max_digits=16, decimal_places=4, allow_inf_nan=False)]
    max_drawdown_pct: float = Field(ge=0, le=100, allow_inf_nan=False)

    @model_validator(mode="after")
    def consistent(self):
        if self.wins + self.losses > self.closed_trades:
            raise ValueError("Wins and losses exceed closed trades")
        today = datetime.now(timezone.utc).date()
        if self.report_date > today or (today - self.report_date).days > 3660:
            raise ValueError("Report date must be within the previous ten years")
        if self.closed_trades == 0 and self.realized_pnl != 0:
            raise ValueError("A closed-trade report without trades must have zero realized PnL")
        return self


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = Store(settings.database_path)
    app = FastAPI(title="ForexLab optional license metadata API", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(RequestBoundary, settings=settings)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts), www_redirect=False)
    app.state.store = store
    failures = WindowLimiter(settings.authentication_failures_per_minute)
    bearer = HTTPBearer(auto_error=False)

    def denied(request):
        failures.allow(request.client.host if request.client else "unknown")
        raise HTTPException(401, "Valid active credential required", headers={"WWW-Authenticate": "Bearer"})

    def credential(request: Request, auth: HTTPAuthorizationCredentials | None = Depends(bearer)):
        ip = request.client.host if request.client else "unknown"
        if not failures.allow(ip, record=False):
            raise HTTPException(429, "Authentication rate exceeded", headers={"Retry-After": "60"})
        if not auth or not 32 <= len(auth.credentials) <= 256 or not auth.credentials.isascii():
            denied(request)
        return auth.credentials

    def admin(request: Request, token: str = Depends(credential)):
        if not hmac.compare_digest(digest(token), digest(settings.admin_token)):
            denied(request)

    def active_license(db, token):
        row = db.execute("SELECT * FROM licenses WHERE key_hash=?", (digest(token),)).fetchone()
        return row if row and not row["revoked"] and math.isfinite(row["expires_at"]) and row["expires_at"] > time.time() else None

    def current_device(db, device_id):
        row = db.execute("""SELECT d.*, l.customer_id, l.expires_at FROM devices d
            JOIN licenses l ON l.id=d.license_id
            WHERE d.id=? AND d.revoked=0 AND l.revoked=0 AND l.expires_at>?""", (device_id, time.time())).fetchone()
        if row is None or not math.isfinite(row["expires_at"]):
            raise HTTPException(401, "Valid active credential required", headers={"WWW-Authenticate": "Bearer"})
        return row

    def customer(request: Request, token: str = Depends(credential)):
        with store.connect() as db:
            row = active_license(db, token)
            if row is None:
                denied(request)
            return dict(row)

    def device(request: Request, token: str = Depends(credential)):
        with store.connect() as db:
            row = db.execute("""SELECT d.*, l.customer_id, l.expires_at FROM devices d
                JOIN licenses l ON l.id=d.license_id
                WHERE d.credential_hash=? AND d.revoked=0 AND l.revoked=0 AND l.expires_at>?""", (digest(token), time.time())).fetchone()
            if row is None or not math.isfinite(row["expires_at"]):
                denied(request)
            return dict(row)

    def license_view(row):
        return {"id": row["id"], "customer_id": row["customer_id"], "expires_at": utc_iso(row["expires_at"]), "seat_limit": row["seat_limit"], "revoked": bool(row["revoked"])}

    def device_view(row):
        return {"id": row["id"], "license_id": row["license_id"], "label": row["label"], "revoked": bool(row["revoked"]), "last_seen": utc_iso(row["last_seen"]), "app_version": row["app_version"]}

    def owned_device(db, device_id, customer_id):
        row = db.execute("""SELECT d.* FROM devices d JOIN licenses l ON l.id=d.license_id
            WHERE d.id=? AND l.customer_id=?""", (device_id, customer_id)).fetchone()
        if row is None:
            raise HTTPException(404, "Device not found")
        return row

    @app.exception_handler(sqlite3.Error)
    async def database_unavailable(request, exc):
        return JSONResponse({"detail": "Metadata storage unavailable"}, status_code=503)

    @app.exception_handler(RequestValidationError)
    async def invalid_payload(request, exc):
        # Do not echo accidental secret fields or non-finite input into responses.
        errors = [{"type": error["type"], "loc": list(error["loc"]), "msg": error["msg"]} for error in exc.errors()]
        return JSONResponse({"detail": errors}, status_code=422)

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "license-metadata", "broker_execution": False}

    @app.get("/portal", include_in_schema=False)
    def portal():
        return FileResponse(Path(__file__).parent / "web" / "portal.html", media_type="text/html")

    @app.get("/portal.js", include_in_schema=False)
    def portal_script():
        return FileResponse(Path(__file__).parent / "web" / "portal.js", media_type="text/javascript")

    @app.get("/portal.css", include_in_schema=False)
    def portal_style():
        return FileResponse(Path(__file__).parent / "web" / "portal.css", media_type="text/css")

    @app.post("/v1/admin/customers", dependencies=[Depends(admin)], status_code=201)
    def create_customer(body: CustomerCreate):
        customer_id = identifier("cus_")
        with store.connect(write=True) as db:
            db.execute("INSERT INTO customers VALUES (?,?,?)", (customer_id, body.name, time.time()))
        return {"id": customer_id, "name": body.name}

    @app.get("/v1/admin/customers", dependencies=[Depends(admin)])
    def list_customers(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0, le=1000000)):
        with store.connect() as db:
            return [dict(row) for row in db.execute("SELECT id,name FROM customers ORDER BY created_at,id LIMIT ? OFFSET ?", (limit, offset))]

    @app.post("/v1/admin/licenses", dependencies=[Depends(admin)], status_code=201)
    def create_license(body: LicenseCreate):
        license_id, key = identifier("lic_"), "fl_license_" + secrets.token_urlsafe(32)
        with store.connect(write=True) as db:
            if db.execute("SELECT id FROM customers WHERE id=?", (body.customer_id,)).fetchone() is None:
                raise HTTPException(404, "Customer not found")
            db.execute("INSERT INTO licenses VALUES (?,?,?,?,?,?,?)", (license_id, body.customer_id, digest(key), body.expires_at.timestamp(), body.seat_limit, 0, time.time()))
            row = db.execute("SELECT * FROM licenses WHERE id=?", (license_id,)).fetchone()
        return {**license_view(row), "license_key": key, "notice": "Shown once. Store securely; this key controls only customer metadata access."}

    @app.get("/v1/admin/licenses", dependencies=[Depends(admin)])
    def list_licenses(customer_id: str = Query(pattern=r"^cus_[a-f0-9]{32}$"), limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0, le=1000000)):
        with store.connect() as db:
            return [license_view(row) for row in db.execute("SELECT * FROM licenses WHERE customer_id=? ORDER BY created_at,id LIMIT ? OFFSET ?", (customer_id, limit, offset))]

    @app.post("/v1/admin/licenses/{license_id}/revoke", dependencies=[Depends(admin)])
    def revoke_license(license_id: str):
        with store.connect(write=True) as db:
            if db.execute("UPDATE licenses SET revoked=1 WHERE id=?", (license_id,)).rowcount != 1:
                raise HTTPException(404, "License not found")
        return {"revoked": True, "notice": "Metadata credentials revoked; existing broker positions are unaffected."}

    @app.post("/v1/admin/devices/{device_id}/revoke", dependencies=[Depends(admin)])
    def admin_revoke_device(device_id: str):
        with store.connect(write=True) as db:
            if db.execute("UPDATE devices SET revoked=1 WHERE id=?", (device_id,)).rowcount != 1:
                raise HTTPException(404, "Device not found")
        return {"revoked": True}

    @app.get("/v1/customer/me")
    def customer_me(principal=Depends(customer)):
        with store.connect() as db:
            row = db.execute("SELECT id,name FROM customers WHERE id=?", (principal["customer_id"],)).fetchone()
            return {"customer": dict(row), "license": license_view(principal)}

    @app.post("/v1/enroll", status_code=201)
    def enroll(body: Enrollment, request: Request, token: str = Depends(credential)):
        device_id, key = identifier("dev_"), "fl_device_" + secrets.token_urlsafe(32)
        with store.connect(write=True) as db:
            principal = active_license(db, token)
            if principal is None:
                denied(request)
            count = db.execute("SELECT COUNT(*) FROM devices WHERE license_id=? AND revoked=0", (principal["id"],)).fetchone()[0]
            if count >= principal["seat_limit"]:
                raise HTTPException(409, "License device seat limit reached; revoke an old device first")
            db.execute("INSERT INTO devices (id,license_id,credential_hash,label,created_at) VALUES (?,?,?,?,?)", (device_id, principal["id"], digest(key), body.label, time.time()))
        return {"device_id": device_id, "device_credential": key, "expires_at": utc_iso(principal["expires_at"]), "notice": "Shown once. Keep this device credential on its Windows bridge; do not share it."}

    @app.get("/v1/customer/devices")
    def customer_devices(principal=Depends(customer), limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0, le=1000000)):
        with store.connect() as db:
            rows = db.execute("""SELECT d.* FROM devices d JOIN licenses l ON l.id=d.license_id
                WHERE l.customer_id=? ORDER BY d.created_at,d.id LIMIT ? OFFSET ?""", (principal["customer_id"], limit, offset))
            return [device_view(row) for row in rows]

    @app.post("/v1/customer/devices/{device_id}/revoke")
    def customer_revoke_device(device_id: str, principal=Depends(customer)):
        with store.connect(write=True) as db:
            owned_device(db, device_id, principal["customer_id"])
            db.execute("UPDATE devices SET revoked=1 WHERE id=?", (device_id,))
        return {"revoked": True}

    @app.post("/v1/device/heartbeat")
    def heartbeat(body: Heartbeat, principal=Depends(device)):
        seen = time.time()
        with store.connect(write=True) as db:
            current_device(db, principal["id"])
            db.execute("UPDATE devices SET last_seen=?,app_version=? WHERE id=?", (seen, body.app_version, principal["id"]))
        return {"device_id": principal["id"], "received_at": utc_iso(seen), "license_expires_at": utc_iso(principal["expires_at"]), "broker_execution": False}

    @app.put("/v1/device/reports")
    def report(body: DailyReport, principal=Depends(device)):
        with store.connect(write=True) as db:
            current_device(db, principal["id"])
            db.execute("""INSERT INTO reports VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(device_id,report_date,currency) DO UPDATE SET
                closed_trades=excluded.closed_trades,wins=excluded.wins,losses=excluded.losses,
                realized_pnl=excluded.realized_pnl,max_drawdown_pct=excluded.max_drawdown_pct,updated_at=excluded.updated_at""", (principal["id"], body.report_date.isoformat(), body.currency, body.closed_trades, body.wins, body.losses, str(body.realized_pnl), body.max_drawdown_pct, time.time()))
        return {"stored": True, "device_id": principal["id"], "verification": "self-reported demo research; not independently verified"}

    @app.get("/v1/customer/performance")
    def performance(principal=Depends(customer), device_id: str | None = Query(None, pattern=r"^dev_[a-f0-9]{32}$"), since: date | None = None, until: date | None = None):
        if since and until and since > until:
            raise HTTPException(422, "since must not follow until")
        with store.connect() as db:
            if device_id:
                owned_device(db, device_id, principal["customer_id"])
            rows = db.execute("""SELECT r.* FROM reports r JOIN devices d ON d.id=r.device_id
                JOIN licenses l ON l.id=d.license_id WHERE l.customer_id=?
                AND (? IS NULL OR d.id=?) AND (? IS NULL OR r.report_date>=?)
                AND (? IS NULL OR r.report_date<=?)""", (principal["customer_id"], device_id, device_id, str(since) if since else None, str(since) if since else None, str(until) if until else None, str(until) if until else None))
            totals = {}
            for row in rows:
                item = totals.setdefault(row["currency"], {"currency": row["currency"], "closed_trades": 0, "wins": 0, "losses": 0, "realized_pnl": Decimal(0), "maximum_reported_daily_drawdown_pct": 0.0, "device_days": 0})
                for field in ("closed_trades", "wins", "losses"):
                    item[field] += row[field]
                item["realized_pnl"] += Decimal(row["realized_pnl"])
                item["maximum_reported_daily_drawdown_pct"] = max(item["maximum_reported_daily_drawdown_pct"], row["max_drawdown_pct"])
                item["device_days"] += 1
        return {"verification": "self-reported demo research; not independently verified", "totals": [{**totals[key], "realized_pnl": str(totals[key]["realized_pnl"])} for key in sorted(totals)], "notice": "Currencies are separate. This summary is not an account equity curve or a guarantee of returns."}

    return app
