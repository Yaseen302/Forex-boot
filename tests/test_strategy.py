import pytest
from backend.market import synthetic, validate, aggregate, close_time
from backend.strategy import analyze, signal


def test_every_timeframe():
    from backend.market import TIMEFRAMES
    for tf in TIMEFRAMES:
        cs=synthetic(tf)
        assert len(cs)==300
        assert analyze(cs)['time']==cs[-1]['time']


def test_deterministic(): assert synthetic()==synthetic()


def test_short_history_fails():
    with pytest.raises(ValueError):analyze(synthetic(count=20))


def test_no_signal_on_mixed_flat_prices():
    cs=[dict(time=i*1800,open=1.,high=1.01,low=.99,close=1.,volume=10.) for i in range(100)]
    assert signal({tf:cs for tf in ('D1','H4','M30')})['side']=='WAIT'


def test_pivot_requires_two_right_candles():
    cs=[dict(time=i*1800,open=1.,high=1.01,low=.99,close=1.,volume=10.) for i in range(35)]
    cs[-2]['high']=1.5
    assert all(x['price']!=1.5 for x in analyze(cs)['swings']['highs'])
    cs.append(dict(time=35*1800,open=1.,high=1.01,low=.99,close=1.,volume=10.))
    assert any(x['price']==1.5 for x in analyze(cs)['swings']['highs'])


def test_bullish_fvg_and_full_mitigation():
    cs=[dict(time=i*1800,open=1.,high=1.01,low=.99,close=1.,volume=10.) for i in range(35)]
    cs[-1].update(open=1.04,high=1.06,low=1.03,close=1.05)
    assert any(z['kind']=='FVG' and z['direction']=='bullish' for z in analyze(cs)['zones'])
    cs.append(dict(time=35*1800,open=1.,high=1.01,low=.98,close=1.,volume=10.))
    assert not any(z['direction']=='bullish' for z in analyze(cs)['zones'])


def test_validation_rejects_duplicate_times():
    cs=synthetic();cs[-1]['time']=cs[-2]['time']
    with pytest.raises(ValueError):validate(cs)


def test_aggregate_does_not_change_input():
    cs=synthetic('M30',100)
    before=[dict(c) for c in cs]
    agg=aggregate(cs,14400)
    assert cs==before
    assert sum(c['volume'] for c in agg)==sum(c['volume'] for c in cs)


def test_month_close_leap_year():
    from datetime import datetime,timezone
    c={'time':int(datetime(2024,2,1,tzinfo=timezone.utc).timestamp())}
    assert close_time(c,'MN1')==int(datetime(2024,3,1,tzinfo=timezone.utc).timestamp())
