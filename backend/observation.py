"""Read-only demo soak evidence. This module cannot enable or submit orders.

Only an allowlisted observation schema is persisted. Account identity is HMACed
with a database-local random salt; raw terminal errors, logins, paths, environment
variables and credentials are never included in samples or exported reports.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
from pathlib import Path
import secrets
import sqlite3
import time
import uuid


# Do not copy arbitrary transport details into a support file, even if they look
# like identifiers: broker exceptions can contain private account information.
BLOCKERS = frozenset('''terminal terminal_trading python_trading account demo_account
account_trading account_state position_capacity symbol symbol_info market_watch
contract_values tick_values filling symbol_trading risk_configuration quote spread
history_D1 history_H4 history_M30 freshness_D1 freshness_H4 freshness_M30
transport_unavailable reading_invalid clock_mismatch account_changed_during_sample
account_identity equity balance margin_free positions pending_orders'''.split())
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / 'runtime' / 'observations.sqlite'


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _utc(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def _count(value):
    number = _number(value)
    return int(number) if number is not None and number >= 0 and number.is_integer() else None


class ObservationStore:
    """Own tables only; may use a separate file or an existing Store.path."""
    def __init__(self, path=DEFAULT_DATABASE):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS observation_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS observation_samples(
                    id INTEGER PRIMARY KEY,run_id TEXT NOT NULL,symbol TEXT NOT NULL,
                    observed_at REAL NOT NULL,payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS observation_symbol ON observation_samples(symbol,id);
            ''')
            db.execute('INSERT OR IGNORE INTO observation_meta VALUES (?,?)', ('identity_salt', secrets.token_hex(32)))
            self._salt = bytes.fromhex(db.execute("SELECT value FROM observation_meta WHERE key='identity_salt'").fetchone()[0])

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def account_hash(self, identity):
        return hmac.new(self._salt, identity.encode('utf-8'), hashlib.sha256).hexdigest()

    def append(self, row):
        with self.connect() as db:
            db.execute('INSERT INTO observation_samples(run_id,symbol,observed_at,payload) VALUES (?,?,?,?)',
                       (row['run_id'], row['symbol'], row['observed_at'], json.dumps(row, allow_nan=False)))

    def samples(self, symbol=None):
        query = 'SELECT payload FROM observation_samples'
        args = ()
        if symbol is not None:
            query += ' WHERE symbol=?'
            args = (symbol,)
        with self.connect() as db:
            rows = db.execute(query + ' ORDER BY id', args).fetchall()
        return [json.loads(row[0]) for row in rows]


class MT5ReadOnlyTransport:
    """All MT5 operations here are queries; the account is checked on both sides.

    A separate process may query MT5 alongside the dashboard. It never selects a
    symbol, logs in, changes settings, constructs an order, or accesses passwords.
    """
    def __init__(self, bridge):
        self.bridge = bridge

    def snapshot(self, symbol, now):
        bridge = self.bridge
        bridge.connect()
        before = bridge.mt.account_info()
        report = bridge.diagnostics(symbol, now=now)
        after = bridge.mt.account_info()
        def identity(account):
            login = getattr(account, 'login', None)
            server = getattr(account, 'server', None)
            if not isinstance(login, int) or isinstance(login, bool) or login <= 0 or not isinstance(server, str) or not server:
                return None
            return f'{server}\x00{login}'
        before_id, after_id = identity(before), identity(after)
        account = report.get('account') or {}
        stable = before_id is not None and before_id == after_id
        demo_constant = getattr(bridge.mt, 'ACCOUNT_TRADE_MODE_DEMO', object())
        demo = stable and getattr(before, 'trade_mode', None) == demo_constant and getattr(after, 'trade_mode', None) == demo_constant and account.get('mode') == 'demo'
        blockers = list(report.get('trading_blockers', []))
        if not stable:
            blockers.append('account_changed_during_sample')
        return dict(account_identity=after_id if stable else None, demo=bool(demo),
                    connected=report.get('connected') is True,
                    ready_for_data=report.get('ready_for_data') is True,
                    ready_for_demo=report.get('ready_for_demo') is True and stable and demo,
                    equity=account.get('equity'), balance=account.get('balance'),
                    margin_free=account.get('margin_free'), positions=report.get('positions'), currency=account.get('currency'),
                    pending_orders=report.get('pending_orders'), quote_time=(report.get('quote') or {}).get('time'),
                    quote_fresh=(report.get('market_activity') or {}).get('state') == 'fresh', blockers=blockers)


class DemoObserver:
    def __init__(self, transport, store, *, clock=time.time, monotonic=time.monotonic, interval_seconds=60):
        interval = _number(interval_seconds)
        if interval is None or not 1 <= interval <= 86400:
            raise ValueError('Observation interval must be between 1 and 86400 seconds')
        self.transport, self.store = transport, store
        self.clock, self.monotonic = clock, monotonic
        self.interval_seconds = interval
        self.run_id = uuid.uuid4().hex
        self.previous = {}

    def sample(self, symbol='EURUSDm', *, reset_comparison=False):
        if not isinstance(symbol, str) or not 1 <= len(symbol) <= 64 or any(ord(c) < 32 for c in symbol):
            raise ValueError('Select an exact broker symbol of 1–64 printable characters')
        now, mono = _number(self.clock()), _number(self.monotonic())
        if now is None or mono is None or not 0 <= now <= 253402300799:
            raise ValueError('Observation clocks must be finite valid timestamps')
        previous = self.previous.get(symbol)
        interval = max(0.0, mono - previous['monotonic']) if previous else 0.0
        clock_bad = bool(previous and (now < previous['observed_at'] or mono < previous['monotonic']))
        try:
            raw = self.transport.snapshot(symbol, now)
            if not isinstance(raw, dict):
                raise ValueError('Invalid snapshot')
        except Exception:
            # No exception text or broker error payload can enter the journal.
            raw = dict(connected=False, blockers=['transport_unavailable'])
        raw_blockers = raw.get('blockers')
        blockers = {value for value in raw_blockers if isinstance(value, str) and value in BLOCKERS} if isinstance(raw_blockers, (list, tuple, set)) else set()
        identity = raw.get('account_identity')
        if not isinstance(identity, str) or not 1 <= len(identity) <= 512:
            identity = None
            blockers.add('account_identity')
        connected, demo = raw.get('connected') is True, raw.get('demo') is True
        currency = raw.get('currency')
        currency = currency if isinstance(currency, str) and 3 <= len(currency) <= 8 and currency.isascii() and currency.isalpha() and currency.isupper() else None
        if not connected:
            blockers.add('terminal')
        if not demo:
            blockers.add('demo_account')
        numeric = {key: _number(raw.get(key)) for key in ('equity', 'balance', 'margin_free')}
        for key, value in numeric.items():
            if value is None or (key in ('equity', 'balance') and value < 0):
                blockers.add(key)
                numeric[key] = None
        counts = {key: _count(raw.get(key)) for key in ('positions', 'pending_orders')}
        blockers.update(key for key, value in counts.items() if value is None)
        if clock_bad:
            blockers.add('clock_mismatch')
        valid = connected and demo and identity is not None and not clock_bad and all(value is not None for value in (*numeric.values(), *counts.values()))
        if not valid:
            blockers.add('reading_invalid')
        quote_time = _number(raw.get('quote_time'))
        if quote_time is not None and not 0 <= quote_time <= 253402300799:
            quote_time = None
        quote_age = now - quote_time if quote_time is not None else None
        quote_fresh = valid and raw.get('quote_fresh') is True and quote_age is not None and 0 <= quote_age <= 30
        if not quote_fresh:
            blockers.add('quote')
        row = dict(run_id=self.run_id, symbol=symbol, observed_at=now, observed_at_utc=_utc(now),
                   interval_seconds=interval, expected_interval_seconds=self.interval_seconds,
                   connected=connected, demo=demo, valid=bool(valid), currency=currency,
                   comparison_reset=bool(reset_comparison),
                   account_hash=self.store.account_hash(identity) if identity is not None else None,
                   ready_for_data=valid and raw.get('ready_for_data') is True,
                   ready_for_demo=valid and raw.get('ready_for_demo') is True and quote_fresh and not blockers,
                   quote_time=quote_time, quote_age_seconds=quote_age, quote_fresh=bool(quote_fresh),
                   blockers=sorted(blockers), **numeric, **counts)
        self.store.append(row)
        self.previous[symbol] = dict(observed_at=now, monotonic=mono)
        return row

    def report(self, symbol=None):
        return observation_report(self.store.samples(symbol))


def observation_report(rows):
    """Pure allowlisted export. Gaps/restarts are not counted as observed uptime."""
    symbols = sorted({row['symbol'] for row in rows})
    if len(symbols) > 1:
        return dict(schema_version=1, read_only=True, symbols={symbol: observation_report([r for r in rows if r['symbol'] == symbol]) for symbol in symbols},
                    notice='Separate symbols are reported separately; durations must not be added together.')
    failures = Counter()
    account, previous, recovering, peak, balance = None, None, False, None, None
    elapsed = covered = connected_seconds = 0.0
    reconnects = disruptions = resets = balance_changes = clock_errors = 0
    drawdown_cash = drawdown_percent = 0.0
    segments, fresh_dates, accounts = [], set(), set()
    for row in rows:
        failures.update(row['blockers'])
        if 'clock_mismatch' in row['blockers']:
            clock_errors += 1
        if previous is not None and row['run_id'] == previous['run_id']:
            delta = row['interval_seconds']
            elapsed += delta
            if 0 <= delta <= 2.5 * row['expected_interval_seconds'] and row['observed_at'] >= previous['observed_at']:
                covered += delta
                if row['valid'] and previous['valid'] and row['account_hash'] == previous['account_hash']:
                    connected_seconds += delta
        if row['valid']:
            current = row['account_hash']
            accounts.add(current)
            if current != account or row.get('comparison_reset', False):
                resets += int(account is not None)
                account, peak, balance, recovering = current, row['equity'], row['balance'], False
                segments.append(dict(account_hash=current, currency=row.get('currency'), first_observed_at_utc=row['observed_at_utc'],
                                     last_observed_at_utc=row['observed_at_utc'], max_observed_drawdown=0.0, max_observed_drawdown_percent=0.0))
            else:
                if recovering:
                    reconnects += 1
                    recovering = False
                if balance != row['balance']:
                    balance_changes += 1
                balance = row['balance']
                peak = max(peak, row['equity'])
            dd = max(0.0, peak - row['equity'])
            pct = dd / peak * 100 if peak > 0 else 0.0
            drawdown_cash, drawdown_percent = max(drawdown_cash, dd), max(drawdown_percent, pct)
            segment = segments[-1]
            segment['last_observed_at_utc'] = row['observed_at_utc']
            segment['max_observed_drawdown'] = max(segment['max_observed_drawdown'], dd)
            segment['max_observed_drawdown_percent'] = max(segment['max_observed_drawdown_percent'], pct)
            if row['quote_fresh']:
                fresh_dates.add(_utc(row['quote_time'])[:10])
        elif account is not None and not recovering:
            disruptions += 1
            recovering = True
        previous = row
    valid_count = sum(row['valid'] for row in rows)
    ready_count = sum(row['ready_for_demo'] for row in rows)
    first, last = (rows[0]['observed_at'], rows[-1]['observed_at']) if rows else (None, None)
    currencies = sorted({row['currency'] for row in rows if row.get('currency') is not None and row['valid']})
    comparable_currency = len(currencies) == 1 and all(row.get('currency') is not None for row in rows if row['valid'])
    return dict(schema_version=1, read_only=True, demo_observation=True, symbol=symbols[0] if symbols else None,
                samples=len(rows), verified_demo_samples=valid_count, failed_samples=len(rows)-valid_count,
                ready_for_demo_samples=ready_count, first_observed_at_utc=_utc(first) if first is not None else None,
                last_observed_at_utc=_utc(last) if last is not None else None,
                wall_span_seconds=max(0.0, last-first) if rows else 0.0,
                actual_observation_seconds=elapsed, covered_interval_seconds=covered,
                verified_connected_interval_seconds=connected_seconds,
                verified_connected_coverage_percent=connected_seconds/covered*100 if covered > 0 else None,
                verified_sample_percent=valid_count/len(rows)*100 if rows else None,
                observed_disruptions=disruptions, verified_reconnect_successes=reconnects,
                unresolved_disruption=recovering, account_comparison_resets=resets, distinct_demo_accounts=len(accounts),
                comparison_segments=segments, currencies=currencies,
                max_observed_equity_drawdown=drawdown_cash if comparable_currency else None,
                max_observed_equity_drawdown_percent=drawdown_percent,
                balance_change_observations=balance_changes, clock_error_samples=clock_errors,
                fresh_quote_utc_dates=sorted(fresh_dates), fresh_quote_date_count=len(fresh_dates),
                blocker_counts=dict(sorted(failures.items())),
                limitations=[
                    'Read-only sampled evidence; no orders are sent and passing checks do not prove broker execution or profit.',
                    'Actual observation seconds use monotonic intervals inside each running collector; restarts are excluded. Wall span can include unobserved gaps.',
                    'Connected coverage requires valid readings at both ends, the same demo account and a gap no greater than 2.5 configured intervals; outages between polls may be missed.',
                    'Reconnect success means a valid reading of the same demo account after a recorded failure; another account resets comparison.',
                    'Equity drawdown is sampled, excludes unknown intrapoll peaks and is not adjusted for deposits, withdrawals or demo resets. Balance changes can also be realized P/L.',
                    'Fresh-quote UTC dates are timestamp evidence only; they do not prove full market sessions, four market days, all market regimes or profitable operation.'
                ])


def main(argv=None):
    parser = argparse.ArgumentParser(description='Read-only demo soak evidence; never enables or sends orders.')
    parser.add_argument('--symbol', default='EURUSDm')
    parser.add_argument('--database', default=str(DEFAULT_DATABASE))
    parser.add_argument('--duration-hours', type=float, default=24)
    parser.add_argument('--interval-seconds', type=float, default=60)
    parser.add_argument('--sample', action='store_true', help='Collect one reading only; records zero elapsed observation time')
    parser.add_argument('--reset-comparison', action='store_true', help='Start a new equity comparison baseline at the first sample; preserve earlier evidence')
    parser.add_argument('--report', action='store_true', help='Report existing evidence without connecting to MT5')
    parser.add_argument('--output', help='Optional allowlisted JSON report file (never a raw database or environment dump)')
    args = parser.parse_args(argv)
    if not math.isfinite(args.duration_hours) or not 0 < args.duration_hours <= 8760:
        parser.error('--duration-hours must be greater than zero and at most 8760')
    if not math.isfinite(args.interval_seconds) or not 1 <= args.interval_seconds <= 86400:
        parser.error('--interval-seconds must be between 1 and 86400')
    store, bridge = ObservationStore(args.database), None
    interrupted = False
    if args.report:
        report = observation_report(store.samples(args.symbol))
    else:
        try:
            from .bridge import MT5Bridge
            bridge = MT5Bridge()
        except Exception:
            print('MT5 observation requires Windows and the project virtual environment with MT5 open. No evidence was fabricated.')
            return 1
        observer = DemoObserver(MT5ReadOnlyTransport(bridge), store, interval_seconds=args.interval_seconds)
        deadline = time.monotonic() + args.duration_hours * 3600
        try:
            first_sample = True
            while True:
                row = observer.sample(args.symbol, reset_comparison=args.reset_comparison and first_sample)
                first_sample = False
                print(json.dumps(dict(observed_at_utc=row['observed_at_utc'], valid_demo_reading=row['valid'],
                                      quote_age_seconds=row['quote_age_seconds'], blockers=row['blockers']), allow_nan=False), flush=True)
                remaining = deadline - time.monotonic()
                if args.sample or remaining <= 0:
                    break
                time.sleep(min(args.interval_seconds, remaining))
        except KeyboardInterrupt:
            interrupted = True
        finally:
            bridge.mt.shutdown()
        report = observer.report(args.symbol)
    rendered = json.dumps(report, indent=2, allow_nan=False)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + '\n', encoding='utf-8')
    print(rendered)
    if interrupted:
        print('Observation stopped by operator. Report contains actual readings only.')
    return 0 if report.get('verified_demo_samples', 0) > 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
