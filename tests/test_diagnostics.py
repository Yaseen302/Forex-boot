"""Operational preflight checks use a fake MT5 transport, never a broker account."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace as NS

import pytest

from backend.bridge import MT5Bridge
from backend.market import synthetic


NOW=1_800_000_005


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO=0
    SYMBOL_TRADE_MODE_FULL=4
    SYMBOL_FILLING_FOK=1
    TIMEFRAME_D1='D1'
    TIMEFRAME_H4='H4'
    TIMEFRAME_M30='M30'

    def __init__(self):
        self.initialize_calls=[]
        self.terminal=NS(connected=True,trade_allowed=True,tradeapi_disabled=False)
        self.account=NS(trade_mode=0,trade_allowed=True,trade_expert=True,currency='USD',
                        server='Exness-MT5Trial',balance=1000,equity=1000,margin_free=1000,
                        login=12345678,name='Private Person',password='never-export-me')
        self.names=['EURUSDm','XAUUSDm']
        self.spec=NS(select=True,digits=5,point=.00001,trade_tick_size=.00001,
                     trade_tick_value=1,trade_tick_value_profit=1,trade_tick_value_loss=1,
                     trade_contract_size=100000,volume_min=.01,volume_max=100,volume_step=.01,
                     trade_stops_level=0,filling_mode=1,trade_mode=4)
        self.tick=NS(bid=1.1,ask=1.1001,time=NOW-1)
        self.positions=[]
        self.orders=[]
        self.rates={tf:[dict(c,tick_volume=c['volume']) for c in synthetic(tf,now=NOW)] for tf in ('D1','H4','M30')}
        self.history_calls=[]

    def initialize(self,*args,**kwargs):
        self.initialize_calls.append((args,kwargs))
        return True

    def terminal_info(self): return self.terminal
    def account_info(self): return self.account
    def positions_get(self): return self.positions
    def orders_get(self): return self.orders
    def symbols_get(self): return [NS(name=n) for n in self.names]
    def symbol_info(self,symbol): return self.spec
    def symbol_info_tick(self,symbol): return self.tick

    def copy_rates_from_pos(self,symbol,tf,start,count):
        self.history_calls.append((symbol,tf,start,count))
        return self.rates[tf][-count:]

    def symbol_select(self,*args): pytest.fail('Read-only preflight must not change Market Watch selection')
    def login(self,*args): pytest.fail('Read-only preflight must not guess or change accounts')
    def order_check(self,*args): pytest.fail('Read-only preflight must not construct an order')
    def order_send(self,*args): pytest.fail('Read-only preflight must never submit an order')


@pytest.fixture
def bridge():
    result=object.__new__(MT5Bridge)
    result.mt=FakeMT5()
    result.terminal_path=None
    result._initialized=False
    return result


def check(report,key):
    return next(item for item in report['checks'] if item['id']==key)


def test_exact_demo_preflight_is_read_only_and_excludes_private_fields(bridge):
    report=bridge.diagnostics('EURUSDm',now=NOW)
    assert report['connected'] and report['ready_for_data'] and report['ready_for_demo']
    assert report['resolved_symbol']=='EURUSDm'
    assert report['positions']==report['pending_orders']==0
    assert set(report['history'])=={'D1','H4','M30'}
    assert bridge.mt.history_calls==[('EURUSDm',tf,1,300) for tf in ('D1','H4','M30')]
    serialized=json.dumps(report,allow_nan=False)
    for secret in ('12345678','Private Person','never-export-me'):
        assert secret not in serialized
    assert all(item['status']=='pass' for item in report['checks'])
    assert report['market_activity']['state']=='fresh'
    assert report['market_activity']['quote_age_seconds']==1
    assert report['trading_blockers']==[]


def test_missing_exact_symbol_suggests_suffix_without_disconnecting_terminal(bridge):
    report=bridge.diagnostics('EURUSD',now=NOW)
    assert report['connected']
    assert not report['ready_for_data'] and not report['ready_for_demo']
    assert report['candidates']==['EURUSDm']
    assert report['resolved_symbol'] is None
    assert not bridge.mt.history_calls
    assert check(report,'symbol')['status']=='fail'


def test_real_account_is_readable_but_never_demo_ready(bridge):
    bridge.mt.account.trade_mode=2
    report=bridge.diagnostics('EURUSDm',now=NOW)
    assert report['ready_for_data'] and not report['ready_for_demo']
    assert report['account']['mode']=='non-demo'
    assert check(report,'demo_account')['status']=='fail'


@pytest.mark.parametrize('field,value,key',[
    ('trade_allowed',False,'terminal_trading'),
    ('tradeapi_disabled',True,'python_trading'),
    ('tradeapi_disabled',None,'python_trading'),
])
def test_terminal_permission_blocks_demo_but_allows_analysis(bridge,field,value,key):
    setattr(bridge.mt.terminal,field,value)
    report=bridge.diagnostics('EURUSDm',now=NOW)
    assert report['ready_for_data'] and not report['ready_for_demo']
    assert check(report,key)['status']=='fail'


def test_initialization_failure_has_actionable_report_without_raw_errors(bridge):
    bridge.mt.initialize=lambda *args:False
    bridge.mt.last_error=lambda:(-1,'secret broker traceback must not leak')
    report=bridge.diagnostics('EURUSDm',now=NOW)
    assert not report['connected'] and not report['ready_for_data']
    assert check(report,'terminal')['action']
    assert 'secret broker traceback' not in json.dumps(report)


def test_terminal_path_is_passed_positionally_and_not_reinitialized(bridge):
    bridge.terminal_path=r'C:\Program Files\Exness MT5\terminal64.exe'
    bridge.connect()
    bridge.account()
    assert bridge.mt.initialize_calls==[((bridge.terminal_path,),{})]
    report=bridge.diagnostics('EURUSDm',now=NOW)
    assert report['terminal']['explicit_path'] is True
    assert bridge.terminal_path not in json.dumps(report)


def test_missing_terminal_allows_explicit_reconnect_on_next_operation(bridge):
    terminal=bridge.mt.terminal
    bridge.mt.terminal=None
    with pytest.raises(RuntimeError,match='unavailable'): bridge.connect()
    bridge.mt.terminal=terminal
    assert bridge.connect() is terminal
    assert len(bridge.mt.initialize_calls)==2


@pytest.mark.parametrize('field,value',[
    ('point',0),('trade_tick_size',float('nan')),('volume_step',0),('volume_max',.001),
])
def test_bad_contract_specs_fail_closed_and_report_json_stays_finite(bridge,field,value):
    setattr(bridge.mt.spec,field,value)
    report=bridge.diagnostics('EURUSDm',now=NOW)
    assert not report['ready_for_data'] and not report['ready_for_demo']
    assert check(report,'contract_values')['status']=='fail'
    json.dumps(report,allow_nan=False)


def test_no_fok_identifies_adapter_limit_without_guessing_ioc(bridge):
    bridge.mt.spec.filling_mode=2
    report=bridge.diagnostics('EURUSDm',now=NOW)
    assert report['ready_for_data'] and not report['ready_for_demo']
    assert not report['symbol']['adapter_fok_supported']
    assert 'separate adapter' in check(report,'filling')['action']


def test_weekend_or_stale_quotes_and_history_block_demo_without_faking_data(bridge):
    bridge.mt.tick.time=NOW-172800
    bridge.mt.rates['M30']=[dict(c,time=c['time']-172800) for c in bridge.mt.rates['M30']]
    report=bridge.diagnostics('EURUSDm',now=NOW)
    assert report['ready_for_data'] and not report['ready_for_demo']
    assert check(report,'quote')['status']=='fail'
    assert check(report,'freshness_M30')['status']=='fail'


@pytest.mark.parametrize('date',['2026-10-17T12:00:00+00:00','2026-10-19T12:00:00+00:00'])
def test_stale_quotes_separate_connection_and_history_from_execution_on_any_day(bridge,date):
    now=datetime.fromisoformat(date).timestamp()
    bridge.mt.tick.time=now-172800
    for tf in bridge.mt.rates:
        bridge.mt.rates[tf]=[dict(c,time=c['time']+int(now-NOW)-172800) for c in bridge.mt.rates[tf]]
    report=bridge.diagnostics('EURUSDm',now=now)
    assert report['connected'] and report['ready_for_data']
    assert not report['ready_for_demo']
    activity=report['market_activity']
    assert activity['state']=='stale' and activity['quote_age_seconds']==172800
    assert 'may be closed or the feed paused' in activity['notice']
    assert 'remain connected' in activity['notice']
    assert 'quote' in report['trading_blockers']
    assert 'freshness_M30' in report['trading_blockers']
    assert check(report,'terminal')['phase']=='connection'
    assert check(report,'history_M30')['phase']=='history'
    assert check(report,'history_M30')['status']=='pass'
    assert check(report,'quote')['phase']==check(report,'freshness_M30')['phase']=='execution'
    assert check(report,'quote')['status']==check(report,'freshness_M30')['status']=='fail'
    json.dumps(report,allow_nan=False)


def test_saturday_alone_does_not_identify_a_closed_session(bridge):
    now=datetime(2026,10,17,12,tzinfo=timezone.utc).timestamp()
    bridge.mt.tick.time=now-1
    report=bridge.diagnostics('EURUSDm',now=now)
    assert report['market_activity']['state']=='fresh'
    assert 'does not confirm an open trading session' in report['market_activity']['notice']


@pytest.mark.parametrize('tick',[None,NS(bid=float('nan'),ask=1.1,time=NOW),NS(bid=1.1,ask=1.2,time=float('inf'))])
def test_unavailable_quote_preserves_connected_history_status_and_serializes_safely(bridge,tick):
    bridge.mt.tick=tick
    report=bridge.diagnostics('EURUSDm',now=NOW)
    assert report['connected'] and report['ready_for_data'] and not report['ready_for_demo']
    assert report['market_activity']['state']=='unavailable'
    assert report['market_activity']['quote_age_seconds'] is None
    assert 'quote' in report['trading_blockers']
    json.dumps(report,allow_nan=False)


def test_overflowing_spread_is_unavailable_and_never_json_infinity(bridge):
    bridge.mt.tick.bid=1e308
    bridge.mt.tick.ask=1.7e308
    bridge.mt.spec.point=1e-308
    report=bridge.diagnostics('EURUSDm',now=NOW)
    assert report['quote']['spread_points'] is None
    assert check(report,'spread')['status']=='fail'
    assert not report['ready_for_demo']
    json.dumps(report,allow_nan=False)


@pytest.mark.parametrize('now',[float('nan'),float('inf'),float('-inf')])
def test_nonfinite_check_time_is_rejected_before_connecting(bridge,now):
    with pytest.raises(ValueError,match='finite timestamp'):
        bridge.diagnostics('EURUSDm',now=now)
    assert not bridge.mt.initialize_calls


def test_bad_history_and_short_history_have_clear_chart_loading_action(bridge):
    bridge.mt.rates['D1']=bridge.mt.rates['D1'][-10:]
    bridge.mt.rates['H4'][-1]['low']=0
    report=bridge.diagnostics('EURUSDm',now=NOW)
    assert not report['ready_for_data'] and not report['ready_for_demo']
    assert check(report,'history_D1')['status']=='fail'
    assert check(report,'history_H4')['status']=='fail'
    assert 'D1 chart' in check(report,'history_D1')['action']


def test_existing_pending_orders_count_towards_position_cap(bridge):
    bridge.mt.orders=[NS(symbol='XAUUSDm')]
    report=bridge.diagnostics('EURUSDm',now=NOW)
    assert report['pending_orders']==1
    assert report['ready_for_data'] and not report['ready_for_demo']
    assert check(report,'position_capacity')['status']=='fail'


def test_unreadable_broker_state_blocks_demo(bridge):
    bridge.mt.positions=None
    report=bridge.diagnostics('EURUSDm',now=NOW)
    assert report['positions'] is None
    assert report['ready_for_data'] and not report['ready_for_demo']
    assert check(report,'account_state')['status']=='fail'


def test_market_watch_not_selected_requires_user_selection(bridge):
    bridge.mt.spec.select=False
    report=bridge.diagnostics('EURUSDm',now=NOW)
    assert not report['ready_for_data'] and not report['ready_for_demo']
    assert 'Market Watch' in check(report,'market_watch')['action']


def test_future_quote_or_history_clock_mismatch_blocks_demo(bridge):
    bridge.mt.tick.time=NOW+10
    bridge.mt.rates['M30']=[dict(c,time=c['time']+1800) for c in bridge.mt.rates['M30']]
    report=bridge.diagnostics('EURUSDm',now=NOW)
    assert report['ready_for_data'] and not report['ready_for_demo']
    assert check(report,'quote')['status']=='fail'
    assert check(report,'freshness_M30')['status']=='fail'
