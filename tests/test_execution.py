from types import SimpleNamespace as NS
import time
import pytest
from backend.execution import execute_demo
from backend.market import synthetic
from backend.store import Store

@pytest.fixture
def harness(tmp_path,monkeypatch):
    import backend.execution as execution
    monkeypatch.setattr(execution.time,'time',lambda:1780000205)
    mt=NS(ACCOUNT_TRADE_MODE_DEMO=0,ORDER_TYPE_BUY=0,ORDER_TYPE_SELL=1,TRADE_ACTION_DEAL=1,ORDER_TIME_GTC=0,ORDER_FILLING_FOK=0,TRADE_RETCODE_DONE=10009)
    a=NS(trade_mode=0,trade_allowed=True,trade_expert=True,equity=10000,margin_free=9000,server='demo',login=123)
    terminal=NS(trade_allowed=True)
    mt.symbol_info=lambda s:NS(point=.00001,trade_tick_size=.00001,digits=5,trade_stops_level=10,volume_min=.01,volume_max=100,volume_step=.01,filling_mode=1)
    mt.symbol_info_tick=lambda s:NS(bid=1.1,ask=1.1001,time=int(time.time()))
    mt.positions_get=lambda:[];mt.orders_get=lambda:[]
    mt.order_calc_profit=lambda k,s,v,e,x:(x-e)*100000
    mt.order_calc_margin=lambda *args:100
    mt.history_deals_get=lambda **kw:[NS(ticket=456,symbol='EURUSD',type=0,volume=mt.last_volume)]
    mt.last_volume=0
    mt.order_check=lambda r:NS(retcode=0)
    def send(r):
        mt.last_volume=r['volume']
        return NS(retcode=10009,order=123,deal=456,volume=r['volume'],price=r['price'])
    mt.order_send=send
    bridge=NS(mt=mt,connect=lambda:terminal,account=lambda:a)
    store=Store(str(tmp_path/'orders.sqlite'));store.set('news_clear_until',time.time()+900)
    frames={tf:synthetic(tf,now=int(time.time())//1800*1800+5) for tf in ('D1','H4','M30')}
    monkeypatch.setattr(execution,'signal',lambda f:dict(side='BUY',stop=1.099,target=1.103,time=f['M30'][-1]['time']))
    return bridge,store,frames,a,mt


def call(h,enabled=True): return execute_demo(h[0],h[1],'EURUSD',h[2],enabled)


def test_disabled_refused(harness):
    with pytest.raises(ValueError,match='disabled'):call(harness,False)


def test_live_refused_before_submission(harness):
    harness[3].trade_mode=2
    harness[4].order_send=lambda r:pytest.fail('Must not send live order')
    with pytest.raises(ValueError,match='DEMO'):call(harness)


def test_valid_demo_and_duplicate(harness):
    assert call(harness)['deal']==456
    with pytest.raises(ValueError,match='Duplicate'):call(harness)


def test_unknown_submission_never_retried(harness):
    harness[4].order_send=lambda r:None
    with pytest.raises(RuntimeError,match='unknown'):call(harness)
    assert harness[1].orders()[0]['status']=='pending'
    with pytest.raises(ValueError,match='Unresolved'):call(harness)


def test_bad_retcode_requires_reconciliation(harness):
    harness[4].order_send=lambda r:NS(retcode=10012,order=0,deal=0,volume=0,price=0)
    with pytest.raises(RuntimeError,match='reconciliation'):call(harness)
    assert harness[1].orders()[0]['status']=='pending'


def test_small_account_refused(harness):
    harness[3].equity=10
    with pytest.raises(ValueError,match='Minimum broker lot'):call(harness)


def test_missing_news_refused(harness):
    harness[1].set('news_clear_until',0)
    with pytest.raises(ValueError,match='News clearance'):call(harness)


def test_stale_quote_refused(harness):
    harness[4].symbol_info_tick=lambda s:NS(bid=1.1,ask=1.1001,time=int(time.time())-60)
    with pytest.raises(ValueError,match='Stale quote'):call(harness)


def test_emergency_refused(harness):
    harness[1].set('emergency',True)
    with pytest.raises(ValueError,match='Emergency'):call(harness)


def test_deal_history_must_confirm(harness):
    harness[4].history_deals_get=lambda **kw:None
    with pytest.raises(RuntimeError,match='history'):call(harness)
    assert harness[1].orders()[0]['status']=='pending'


def test_position_limit_covers_other_symbols(harness):
    harness[4].positions_get=lambda:[NS(symbol='XAUUSD')]
    with pytest.raises(ValueError,match='Position limit'):call(harness)
