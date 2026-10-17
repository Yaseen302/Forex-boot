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
