"""Read-only soak evidence, with fake clocks and no running broker terminal."""
import json
from types import SimpleNamespace as NS

import pytest

from backend.observation import DemoObserver, MT5ReadOnlyTransport, ObservationStore, main, observation_report


class Clock:
    def __init__(self):
        self.wall = 1_792_080_000.0
        self.mono = 100.0

    def advance(self, seconds):
        self.wall += seconds
        self.mono += seconds


def snapshot(account='Exness-Trial\x0012345678', equity=1000, **updates):
    result = dict(account_identity=account, connected=True, demo=True, currency='USD',
                  equity=equity, balance=1000, margin_free=900, positions=0,
                  pending_orders=0, ready_for_data=True, ready_for_demo=True,
                  quote_fresh=True, blockers=[])
    result.update(updates)
    return result


class Transport:
    def __init__(self, value=None):
        self.value = snapshot() if value is None else value
        self.calls = []

    def snapshot(self, symbol, now):
        self.calls.append((symbol, now))
        if isinstance(self.value, Exception):
            raise self.value
        return dict(self.value, quote_time=self.value.get('quote_time', now-1))

    def order_send(self, *args):
        pytest.fail('The observer must never send orders')

    def order_check(self, *args):
        pytest.fail('The observer must never construct/check an order')

    def login(self, *args):
        pytest.fail('The observer must never change or supply broker login')


def observer(tmp_path, transport=None, clock=None):
    clock = clock or Clock()
    return DemoObserver(transport or Transport(), ObservationStore(tmp_path/'observations.sqlite'),
                        clock=lambda: clock.wall, monotonic=lambda: clock.mono), clock


def test_one_sample_is_read_only_and_never_claims_requested_duration(tmp_path):
    transport = Transport()
    subject, clock = observer(tmp_path, transport)
    row = subject.sample()
    report = subject.report()
    assert transport.calls == [('EURUSDm', clock.wall)]
    assert row['valid'] and row['ready_for_demo']
    assert report['samples'] == report['verified_demo_samples'] == 1
    assert report['actual_observation_seconds'] == report['covered_interval_seconds'] == 0
    assert report['verified_connected_coverage_percent'] is None
    assert report['fresh_quote_date_count'] == 1
    assert report['max_observed_equity_drawdown'] == 0


def test_only_allowlisted_fields_leave_memory_and_identity_is_hashed(tmp_path):
    transport = Transport(snapshot(password='password-never-export', API_TOKEN='token-never-export',
                                   terminal_path=r'C:\Users\Secret\terminal64.exe',
                                   blockers=['quote', 'secret-blocker-never-export']))
    subject, _ = observer(tmp_path, transport)
    row = subject.sample()
    exported = json.dumps([row, subject.report(), subject.store.samples()], allow_nan=False)
    for secret in ('12345678', 'Exness-Trial', 'password-never-export', 'token-never-export', 'Secret', 'secret-blocker-never-export'):
        assert secret not in exported
        assert secret.encode() not in (tmp_path/'observations.sqlite').read_bytes()
    assert len(row['account_hash']) == 64
    assert row['blockers'] == ['quote']
    assert not row['ready_for_demo']


def test_same_account_hash_persists_across_process_sessions_but_not_databases(tmp_path):
    first, clock = observer(tmp_path)
    initial = first.sample()
    clock.advance(60)
    restarted, _ = observer(tmp_path, clock=clock)
    assert restarted.sample()['account_hash'] == initial['account_hash']
    elsewhere = ObservationStore(tmp_path/'other.sqlite')
    assert elsewhere.account_hash('Exness-Trial\x0012345678') != initial['account_hash']
    report = restarted.report()
    assert report['distinct_demo_accounts'] == 1
    assert report['account_comparison_resets'] == 0
    assert report['actual_observation_seconds'] == 0  # restart gap is not observed uptime
    assert report['wall_span_seconds'] == 60


def test_disconnect_and_recovery_are_counted_after_verified_same_account(tmp_path):
    transport = Transport()
    subject, clock = observer(tmp_path, transport)
    subject.sample()
    clock.advance(60)
    subject.sample()
    clock.advance(60)
    transport.value = RuntimeError('broker-account-password-never-export')
    failed = subject.sample()
    clock.advance(60)
    subject.sample()
    clock.advance(60)
    transport.value = snapshot(equity=950)
    subject.sample()
    report = subject.report()
    assert failed['connected'] is False and failed['valid'] is False
    assert report['actual_observation_seconds'] == 240
    assert report['covered_interval_seconds'] == 240
    assert report['verified_connected_interval_seconds'] == 60
    assert report['observed_disruptions'] == report['verified_reconnect_successes'] == 1
    assert report['failed_samples'] == 2
    assert report['max_observed_equity_drawdown'] == 50
    assert report['max_observed_equity_drawdown_percent'] == 5
    assert 'broker-account-password' not in json.dumps(report)


def test_recovery_evidence_survives_restart_but_never_fills_unobserved_gap(tmp_path):
    transport = Transport()
    subject, clock = observer(tmp_path, transport)
    subject.sample()
    clock.advance(60)
    transport.value = RuntimeError('disconnect')
    subject.sample()
    clock.advance(3600)
    restarted, _ = observer(tmp_path, Transport(snapshot(equity=900)), clock)
    restarted.sample()
    report = restarted.report()
    assert report['verified_reconnect_successes'] == 1
    assert report['actual_observation_seconds'] == 60
    assert report['wall_span_seconds'] == 3660
    assert report['max_observed_equity_drawdown_percent'] == 10


def test_account_switch_resets_equity_comparison_and_is_not_reconnect(tmp_path):
    transport = Transport()
    subject, clock = observer(tmp_path, transport)
    subject.sample()
    clock.advance(60)
    transport.value = snapshot(equity=800)
    subject.sample()
    clock.advance(60)
    transport.value = RuntimeError('disconnect')
    subject.sample()
    clock.advance(60)
    transport.value = snapshot(account='Exness-Trial\x0087654321', equity=50, balance=50)
    subject.sample()
    report = subject.report()
    assert report['distinct_demo_accounts'] == 2
    assert report['account_comparison_resets'] == 1
    assert report['verified_reconnect_successes'] == 0
    assert not report['unresolved_disruption']
    assert report['max_observed_equity_drawdown_percent'] == 20
    assert report['comparison_segments'][-1]['max_observed_drawdown'] == 0


def test_explicit_demo_reset_starts_new_comparison_without_erasing_evidence(tmp_path):
    transport = Transport()
    subject, clock = observer(tmp_path, transport)
    subject.sample()
    clock.advance(60)
    transport.value = snapshot(equity=900)
    subject.sample()
    clock.advance(60)
    transport.value = snapshot(equity=50, balance=50)
    subject.sample(reset_comparison=True)
    report = subject.report()
    assert report['samples'] == 3
    assert report['distinct_demo_accounts'] == 1
    assert report['account_comparison_resets'] == 1
    assert report['max_observed_equity_drawdown'] == 100
    assert len(report['comparison_segments']) == 2


@pytest.mark.parametrize('updates', [
    {'equity': float('nan')}, {'equity': float('inf')}, {'balance': -1},
    {'positions': None}, {'positions': True}, {'pending_orders': -1},
    {'margin_free': None}, {'connected': 'true'}, {'demo': False},
    {'account_identity': ''},
])
def test_invalid_readings_are_failures_not_successes(tmp_path, updates):
    subject, _ = observer(tmp_path, Transport(snapshot(**updates)))
    row = subject.sample()
    assert not row['valid'] and not row['ready_for_demo']
    report = subject.report()
    assert report['verified_demo_samples'] == 0 and report['failed_samples'] == 1
    assert report['fresh_quote_date_count'] == 0
    json.dumps(report, allow_nan=False)


def test_stale_and_future_quotes_do_not_claim_market_day_coverage(tmp_path):
    clock = Clock()
    transport = Transport(snapshot(quote_time=clock.wall-172800))
    subject, _ = observer(tmp_path, transport, clock)
    row = subject.sample()
    assert row['valid'] and not row['quote_fresh'] and not row['ready_for_demo']
    clock.advance(60)
    transport.value = snapshot(quote_time=clock.wall+1)
    subject.sample()
    assert subject.report()['fresh_quote_date_count'] == 0


def test_clock_rollback_and_long_gaps_cannot_manufacture_uptime(tmp_path):
    subject, clock = observer(tmp_path)
    subject.sample()
    clock.advance(3600)
    subject.sample()
    clock.mono += 60
    clock.wall -= 10
    row = subject.sample()
    report = subject.report()
    assert not row['valid'] and 'clock_mismatch' in row['blockers']
    assert report['clock_error_samples'] == 1
    assert report['actual_observation_seconds'] == 3660
    assert report['covered_interval_seconds'] == 0
    assert report['verified_connected_interval_seconds'] == 0


def test_per_symbol_durations_are_not_added_as_total_uptime(tmp_path):
    subject, clock = observer(tmp_path)
    subject.sample('EURUSDm')
    subject.sample('GBPUSDm')
    clock.advance(60)
    subject.sample('EURUSDm')
    subject.sample('GBPUSDm')
    report = subject.report()
    assert set(report['symbols']) == {'EURUSDm', 'GBPUSDm'}
    assert report['symbols']['EURUSDm']['actual_observation_seconds'] == 60
    assert 'actual_observation_seconds' not in report


def test_mixed_currencies_never_get_a_combined_cash_drawdown(tmp_path):
    transport = Transport()
    subject, clock = observer(tmp_path, transport)
    subject.sample()
    clock.advance(60)
    transport.value = snapshot(account='Other\x0012345', currency='EUR')
    subject.sample()
    report = subject.report()
    assert report['currencies'] == ['EUR', 'USD']
    assert report['max_observed_equity_drawdown'] is None


def test_report_only_does_not_connect_or_require_windows(tmp_path, capsys):
    subject, _ = observer(tmp_path)
    subject.sample()
    target = tmp_path/'support.json'
    result = main(['--database', subject.store.path, '--report', '--output', str(target)])
    assert result == 0
    report = json.loads(target.read_text())
    assert report['samples'] == 1
    assert report['actual_observation_seconds'] == 0
    assert '12345678' not in capsys.readouterr().out


def test_transport_uses_only_read_queries_and_rejects_mid_sample_account_switch():
    account = NS(login=12345678, server='Exness-Trial', trade_mode=0)
    calls = []
    class MT:
        ACCOUNT_TRADE_MODE_DEMO = 0
        def account_info(self):
            calls.append('account_info')
            return account
        def order_send(self, *args): pytest.fail('No orders')
        def order_check(self, *args): pytest.fail('No order checks')
        def login(self, *args): pytest.fail('No login')
    class Bridge:
        mt = MT()
        def connect(self): calls.append('connect')
        def diagnostics(self, symbol, now):
            calls.append(('diagnostics', symbol, now))
            return dict(connected=True, ready_for_data=True, ready_for_demo=True,
                        account=dict(mode='demo', equity=1000, balance=1000, margin_free=900, currency='USD'),
                        positions=0, pending_orders=0, quote=dict(time=now-1),
                        market_activity=dict(state='fresh'), trading_blockers=[])
    transport = MT5ReadOnlyTransport(Bridge())
    result = transport.snapshot('EURUSDm', 1800000000)
    assert result['demo'] and result['account_identity'].endswith('\x0012345678')
    assert calls == ['connect', 'account_info', ('diagnostics', 'EURUSDm', 1800000000), 'account_info']
    before = account
    switched = NS(login=87654321, server='Exness-Trial', trade_mode=0)
    values = iter([before, switched])
    transport.bridge.mt.account_info = lambda: next(values)
    changed = transport.snapshot('EURUSDm', 1800000000)
    assert changed['account_identity'] is None and not changed['demo']
    assert 'account_changed_during_sample' in changed['blockers']


def test_empty_report_is_explicitly_missing_evidence():
    report = observation_report([])
    assert report['samples'] == report['actual_observation_seconds'] == 0
    assert report['verified_sample_percent'] is None
    assert report['fresh_quote_utc_dates'] == []
