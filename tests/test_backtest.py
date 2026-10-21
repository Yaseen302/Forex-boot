import pytest
from backend.market import synthetic
from backend.backtest import run


def test_too_short_rejected():
    with pytest.raises(ValueError,match='1600'):run(synthetic(count=300))


def test_deterministic_empty_run_does_not_claim_win_rate():
    cs=[dict(time=i*1800,open=1.,high=1.01,low=.99,close=1.,volume=10.) for i in range(1601)]
    r=run(cs)
    assert r['trades']==0 and r['win_rate'] is None and r['profit_factor'] is None
    assert r['final']==1000


def test_entry_candle_stop_first_and_costs(monkeypatch):
    import backend.backtest as bt
    cs=[dict(time=i*1800,open=1.1,high=1.11,low=1.09,close=1.1,volume=10.) for i in range(1602)]
    def fake(frames,**kwargs):
        # Verify higher-frame candles really finished before the signal boundary.
        boundary=frames['M30'][-1]['time']+1800
        assert all(c['time']+86400<=boundary for c in frames['D1'])
        assert all(c['time']+14400<=boundary for c in frames['H4'])
        return dict(side='BUY',stop=1.099,target=1.104,time=boundary-1800)
    monkeypatch.setattr(bt,'signal',fake)
    r=run(cs,initial=10000,spread=.0001,slippage=.00005,commission=7)
    assert r['trades']>0
    assert all(t['reason']=='stop' and t['pnl']<0 for t in r['ledger'])
    assert r['net']==pytest.approx(sum(t['pnl'] for t in r['ledger']))
    assert r['final']<10000


def test_carried_exit_cannot_fund_trade_at_same_candle_open(monkeypatch):
    import backend.backtest as bt
    cs=[dict(time=i*1800,open=1.1,high=1.1002,low=1.0998,close=1.1,volume=10.) for i in range(1603)]
    cs[1501]['high']=1.105
    monkeypatch.setattr(bt,'signal',lambda frames,**kw:dict(side='BUY',stop=1.099,target=1.104,time=frames['M30'][-1]['time']))
    r=run(cs,initial=10000,spread=0,slippage=0,commission=0)
    assert r['ledger'][0]['time']==cs[1500]['time']
    assert r['ledger'][0]['exit_time']==cs[1501]['time']
    assert not any(t['time']==cs[1501]['time'] for t in r['ledger'])


def test_history_gap_cannot_replay_old_m30_signal(monkeypatch):
    import backend.backtest as bt
    cs=[dict(time=i*1800,open=1.1,high=1.1002,low=1.0998,close=1.1,volume=10.) for i in range(1603)]
    for i in range(1501,len(cs)): cs[i]['time']+=3*86400
    def only_old_setup(frames,**kw):
        if frames['M30'][-1]['time']==1500*1800:
            return dict(side='BUY',stop=1.099,target=1.104,time=1500*1800)
        return {'side':'WAIT'}
    monkeypatch.setattr(bt,'signal',only_old_setup)
    r=run(cs,spread=0,slippage=0,commission=0)
    assert r['trades']==0


def test_opening_gap_through_stop_is_skipped_even_if_spread_masks_it(monkeypatch):
    import backend.backtest as bt
    cs=[dict(time=i*1800,open=1.1,high=1.1002,low=1.0998,close=1.1,volume=10.) for i in range(1602)]
    cs[1500].update(open=1.099,high=1.1002,low=1.0989,close=1.1)
    def setup(frames,**kwargs):
        return (dict(side='BUY',stop=1.0991,target=1.104,time=1499*1800)
                if frames['M30'][-1]['time']==1499*1800 else {'side':'WAIT'})
    monkeypatch.setattr(bt,'signal',setup)
    result=run(cs,spread=.0002,slippage=0,commission=0)
    assert result['entries']==0 and result['skipped']==1


def test_daily_entry_cap_and_curve_include_floating_equity(monkeypatch):
    import backend.backtest as bt
    cs=[dict(time=i*1800,open=1.1,high=1.105,low=1.0998,close=1.1,volume=10.) for i in range(1602)]
    monkeypatch.setattr(bt,'signal',lambda frames,**kw:dict(side='BUY',stop=1.099,target=1.104,time=frames['M30'][-1]['time']))
    r=run(cs,initial=10000,spread=0,slippage=0,commission=0,max_entries_per_day=2)
    assert r['maximum_daily_entries']==2
    assert len(r['equity_curve'])==len(cs)-1500
    assert all(point['equity']==point['balance'] for point in r['equity_curve'])


def test_mark_to_market_drawdown_sees_unrealized_loss(monkeypatch):
    import backend.backtest as bt
    cs=[dict(time=i*1800,open=1.1,high=1.1001,low=1.0999,close=1.1,volume=10.) for i in range(1602)]
    cs[1500].update(low=1.091,close=1.092)
    monkeypatch.setattr(bt,'signal',lambda frames,**kw:dict(side='BUY',stop=1.09,target=1.13,time=frames['M30'][-1]['time']))
    r=run(cs,initial=10000,spread=0,slippage=0,commission=0)
    assert r['equity_curve'][0]['equity']<r['equity_curve'][0]['balance']
    assert r['max_mark_to_market_drawdown_percent']>r['max_closed_equity_drawdown_percent']


@pytest.mark.parametrize('cost', ['spread','commission','slippage','swap_per_lot_day'])
def test_nonfinite_costs_rejected(cost):
    cs=[dict(time=i*1800,open=1.,high=1.01,low=.99,close=1.,volume=10.) for i in range(1601)]
    with pytest.raises(ValueError,match='Invalid backtest'):run(cs,**{cost:float('nan')})
