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
