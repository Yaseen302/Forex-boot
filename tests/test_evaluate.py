from backend.evaluate import uncertainty,evaluate
import pytest


def test_sparse_trades_do_not_emit_meaningless_confidence():
    result=uncertainty([{'pnl':10.}]*5)
    assert result['status']=='insufficient_trades' and result['expectancy_95_interval'] is None


def test_trade_uncertainty_is_deterministic_and_warns_about_independence():
    ledger=[{'pnl':x} for x in ([1.,-1.,3.,-2.]*15)]
    a=uncertainty(ledger);b=uncertainty(ledger)
    assert a==b
    assert a['expectancy_95_interval'][0]<.25<a['expectancy_95_interval'][1]
    assert 'serial dependence' in a['limitations']


def test_chronological_sections_never_trade_warmup_or_overlap_own_boundaries(monkeypatch):
    import backend.evaluate as ev
    calls=[]
    def capture(candles,entry_start,**kwargs):
        calls.append((candles[entry_start]['time'],candles[-1]['time']))
        return dict(initial=1000,net=0,ledger=[])
    monkeypatch.setattr(ev,'run',capture)
    cs=[dict(time=i*1800,open=1.,high=1.01,low=.99,close=1.,volume=10.) for i in range(8000)]
    result=evaluate(cs,spread=.001,slippage=0,commission=0,swap_per_lot_day=0)
    assert calls[:3]==[(1500*1800,4799*1800),(4800*1800,6399*1800),(6400*1800,7999*1800)]
    assert result['sections'][1]['start_time']==4800*1800
    assert result['sections'][2]['start_time']==6400*1800
    assert len(calls)==6


def test_insufficient_chronological_data_rejected():
    with pytest.raises(ValueError,match='8000'):
        evaluate([dict(time=0,open=1,high=1,low=1,close=1,volume=1)])
